"""dataset.json -> RLDec input folder (<work>/data/<app>/).

Generated files (parquet format expected by rldec.data_handler.DataHandler):
    class_interactions.parquet  N x N DataFrame (index=classes, columns=classes) of structural edge weights
    class_word_count.parquet    N x N DataFrame (index=classes, columns=classes) semantic similarity matrix:
                                  S = W_filtered @ W_filtered.T where W is the N x M Bag-of-Words matrix over
                                  class source files (or dataset.json fallback tokens) filtered to columns with
                                  document frequency <= max(1, N // 2) (falling back to unfiltered W if empty).
                                Matches Khaled Sellami's formula in rldec/callbacks.py:76-78 and satisfies
                                rldec/features.py:47's both_axes=True N x N shape assertion without modifying
                                the upstream submodule.
    class_tfidf.parquet         N x M TF-IDF DataFrame (index=classes) used by DataHandler.get_names().
    class_names.json            Ordered list of class FQNs.
"""

from collections import Counter
import json
import os
from pathlib import Path
import re

import numpy as np
import pandas as pd

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_WORD_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")
_COMMENT_RE = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/")
_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)

_NOISE_WORDS = frozenset({
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "collection", "const", "continue", "default", "do", "double", "else",
    "enum", "extends", "false", "final", "finally", "float", "for", "goto", "if",
    "implements", "import", "instanceof", "int", "integer", "interface", "iterable",
    "list", "long", "map", "native", "new", "null", "object", "optional", "override",
    "package", "private", "protected", "public", "return", "set", "short", "static",
    "strictfp", "string", "super", "switch", "synchronized", "this", "throw",
    "throws", "transient", "true", "try", "void", "volatile", "while",
})

_SKIP_DIRS = frozenset({".git", "target", "build", "node_modules", "test", "tests"})


def collect_classes(dataset):
    """Sorted unique Java class FQNs from dataset.json (classes, methods, edges)."""
    classes = set(dataset.get("classes", ()))
    classes.update(mid.rsplit(".", 1)[0] for mid in dataset.get("methods", {}))
    for edge in dataset.get("edges", []):
        classes.update((edge["src"], edge["dst"]))
    return sorted(classes)


def tokenize_identifier(identifier, min_len=2):
    """Split a Java identifier into lowercase camelCase/snake_case domain terms."""
    tokens = []
    for part in identifier.split("_"):
        if not part:
            continue
        for word in _WORD_RE.findall(part):
            low = word.lower()
            if len(low) >= min_len and low not in _NOISE_WORDS:
                tokens.append(low)
    return tokens


def tokenize_java_source(source_text):
    """Extract Bag-of-Words tokens from Java source code with comments stripped."""
    cleaned = _COMMENT_RE.sub(" ", source_text)
    tokens = []
    for ident in _IDENT_RE.findall(cleaned):
        tokens.extend(tokenize_identifier(ident, min_len=2))
    return tokens


def _resolve_source_root(dataset, dataset_dir):
    source_path = dataset.get("source_path")
    if not source_path:
        return None
    if os.path.isabs(source_path):
        return source_path if os.path.isdir(source_path) else None
    if dataset_dir:
        candidate = os.path.abspath(os.path.join(dataset_dir, source_path))
        if os.path.isdir(candidate):
            return candidate
    candidate = os.path.abspath(source_path)
    return candidate if os.path.isdir(candidate) else None


def _find_production_roots(source_root):
    """Mirror Extractor.findSourceRoots: */src/main/java, else src/, else repo root."""
    root_path = Path(source_root)
    main_java = []
    for dirpath, dirnames, _ in os.walk(root_path):
        dirnames[:] = [d for d in sorted(dirnames) if d not in _SKIP_DIRS]
        p = Path(dirpath)
        if p.parts[-3:] == ("src", "main", "java"):
            main_java.append(p)
    if main_java:
        return sorted(main_java)
    src = root_path / "src"
    return [src] if src.is_dir() else [root_path]


def _resolve_class_files(dataset, classes, dataset_dir, source_root):
    """Map class FQNs -> .java file paths using methods[*].file_path then source_root walk."""
    class_files = {}
    search_bases = [b for b in (source_root, dataset_dir) if b]

    for mid, mdata in dataset.get("methods", {}).items():
        cls = mid.rsplit(".", 1)[0]
        fp = mdata.get("file_path")
        if not fp or cls in class_files:
            continue
        candidates = [fp] if os.path.isabs(fp) else [os.path.join(b, fp) for b in search_bases]
        for cand in candidates:
            if os.path.isfile(cand):
                class_files[cls] = cand
                break

    missing = [c for c in classes if c not in class_files]
    if missing and source_root:
        top_level_map = {}
        for prod_root in _find_production_roots(source_root):
            for dirpath, dirnames, filenames in os.walk(prod_root):
                dirnames[:] = [d for d in sorted(dirnames) if d not in _SKIP_DIRS]
                for fname in sorted(filenames):
                    if not fname.endswith(".java"):
                        continue
                    fpath = os.path.join(dirpath, fname)
                    try:
                        text = Path(fpath).read_text(encoding="utf-8", errors="ignore")
                    except OSError:
                        continue
                    pkg_match = _PACKAGE_RE.search(text)
                    pkg = pkg_match.group(1) if pkg_match else ""
                    stem = fname[:-5]
                    fqn = f"{pkg}.{stem}" if pkg else stem
                    top_level_map.setdefault(fqn, fpath)

        for cls in missing:
            probe = cls
            while probe:
                if probe in top_level_map:
                    class_files[cls] = top_level_map[probe]
                    break
                if "." not in probe:
                    break
                probe = probe.rsplit(".", 1)[0]

    return class_files


def _fallback_tokens_for_class(cls, methods_by_class):
    """Extract camelCase tokens from class name and method signatures in dataset.json."""
    tokens = tokenize_identifier(cls.rsplit(".", 1)[-1], min_len=1)
    for mdata in methods_by_class.get(cls, ()):
        mname = mdata.get("method_name", "")
        if mname and mname != "<init>":
            tokens.extend(tokenize_identifier(mname, min_len=1))
        ret = mdata.get("return_type", "")
        if ret:
            tokens.extend(tokenize_identifier(ret.rsplit(".", 1)[-1], min_len=1))
        for param in mdata.get("parameters", []):
            tokens.extend(tokenize_identifier(param.rsplit(".", 1)[-1], min_len=1))
    return tokens


def build_rldec_inputs(dataset, dataset_dir, out_dir):
    """Convert dataset.json into RLDec's parquet matrices inside out_dir."""
    classes = collect_classes(dataset)
    n = len(classes)
    if n == 0:
        raise ValueError("dataset has no classes")
    index = {cls: i for i, cls in enumerate(classes)}

    # 1. N x N structural interaction matrix from dataset["edges"]
    interactions = np.zeros((n, n), dtype=np.float32)
    for edge in dataset.get("edges", []):
        src, dst = edge["src"], edge["dst"]
        if src != dst and src in index and dst in index:
            interactions[index[src], index[dst]] += float(edge.get("weight", 1.0))

    # 2. N x M Bag-of-Words matrix W from .java files (with dataset.json fallback)
    source_root = _resolve_source_root(dataset, dataset_dir)
    class_files = _resolve_class_files(dataset, classes, dataset_dir, source_root)

    methods_by_class = {}
    for mid, mdata in dataset.get("methods", {}).items():
        methods_by_class.setdefault(mid.rsplit(".", 1)[0], []).append(mdata)

    source_cache = {}
    class_tokens = {}
    java_files_matched = 0
    for cls in classes:
        fpath = class_files.get(cls)
        tokens = []
        if fpath:
            if fpath not in source_cache:
                try:
                    source_cache[fpath] = Path(fpath).read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    source_cache[fpath] = ""
            if source_cache[fpath]:
                java_files_matched += 1
                tokens = tokenize_java_source(source_cache[fpath])
        if not tokens:
            tokens = _fallback_tokens_for_class(cls, methods_by_class)
        class_tokens[cls] = Counter(tokens)

    vocab = sorted({tok for counts in class_tokens.values() for tok in counts})
    vocab_idx = {tok: j for j, tok in enumerate(vocab)}
    m = len(vocab)

    if m > 0:
        bow = np.zeros((n, m), dtype=np.float32)
        for cls in classes:
            i = index[cls]
            for tok, count in class_tokens[cls].items():
                bow[i, vocab_idx[tok]] = float(count)

        # Khaled Sellami's formula (rldec/callbacks.py:76-77):
        # keep terms appearing in <= max(1, N // 2) classes, fallback to unfiltered W if all exceed threshold
        doc_freq = (bow > 0).sum(axis=0)
        threshold = max(1, n // 2)
        keep = doc_freq <= threshold
        bow_filtered = bow[:, keep] if np.any(keep) else bow
        filtered_vocab = int(bow_filtered.shape[1])
        semantic = (bow_filtered @ bow_filtered.T).astype(np.float32)

        idf = np.log((1.0 + n) / (1.0 + doc_freq)) + 1.0
        tfidf = (bow * idf).astype(np.float32)
        df_tfidf = pd.DataFrame(tfidf, index=classes, columns=vocab)
    else:
        filtered_vocab = 0
        semantic = np.zeros((n, n), dtype=np.float32)
        df_tfidf = pd.DataFrame(np.zeros((n, 1), dtype=np.float32), index=classes, columns=["__empty__"])

    df_interactions = pd.DataFrame(interactions, index=classes, columns=classes)
    df_word_count = pd.DataFrame(semantic, index=classes, columns=classes)

    os.makedirs(out_dir, exist_ok=True)
    df_interactions.to_parquet(os.path.join(out_dir, "class_interactions.parquet"))
    df_word_count.to_parquet(os.path.join(out_dir, "class_word_count.parquet"))
    df_tfidf.to_parquet(os.path.join(out_dir, "class_tfidf.parquet"))
    with open(os.path.join(out_dir, "class_names.json"), "w", encoding="utf-8") as f:
        json.dump(classes, f, indent=2)

    semantic_offdiag = semantic.copy()
    np.fill_diagonal(semantic_offdiag, 0.0)
    return {
        "classes": n,
        "vocab": m,
        "filtered_vocab": filtered_vocab,
        "edges": int(np.count_nonzero(interactions)),
        "semantic_pairs": int(np.count_nonzero(semantic_offdiag)),
        "java_files_matched": java_files_matched,
    }
