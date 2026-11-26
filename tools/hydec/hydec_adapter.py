"""Adapter: dataset.json (+ optional Java sources / fosci_trace.csv.gz) -> decomp-hydec input directory.

Generated files under `out_dir`:
    structural/class_names.json   sorted class FQNs (length N)
    structural/class_calls.npy    N x N directed dependency weight matrix from dataset.json["edges"]
    semantic/class_names.json     same sorted class FQNs (length N)
    semantic/class_tfidf.npy      N x M TF-IDF matrix over class Java sources (or dataset.json fallback)
    dynamic/class_names.json      sorted traced class FQNs (length M <= N, only for --approach hyDec)
    dynamic/class_calls.npy       M x M directed runtime call counts from fosci_trace.csv.gz (hyDec only)
"""

import csv
import gzip
import json
import os
import re
from collections import defaultdict

_WORD_RE = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z][a-z]|\d|\W|$)")
_PKG_IMPORT_RE = re.compile(r"^\s*(?:package|import)\s+[^;]+;\s*$", re.MULTILINE)

_JAVA_NOISE = frozenset({
    "abstract", "assert", "boolean", "break", "byte", "case", "catch", "char",
    "class", "const", "continue", "default", "do", "double", "else", "enum",
    "extends", "false", "final", "finally", "float", "for", "goto", "if",
    "implements", "import", "instanceof", "int", "interface", "long", "native",
    "new", "null", "override", "package", "private", "protected", "public",
    "return", "serialversionuid", "short", "static", "strictfp", "string",
    "super", "suppresswarnings", "switch", "synchronized", "this", "throw",
    "throws", "transient", "true", "try", "void", "volatile", "while",
    "object", "integer", "list", "map", "set", "collection", "iterable", "optional",
})


def load_classes(dataset):
    """Sorted unique class FQNs from dataset.json (classes, methods, edges)."""
    classes = set(dataset.get("classes", ()))
    for mid in dataset.get("methods", {}):
        if "." in mid:
            classes.add(mid.rsplit(".", 1)[0])
    for edge in dataset.get("edges", []):
        src = edge.get("src")
        dst = edge.get("dst")
        if src:
            classes.add(src)
        if dst:
            classes.add(dst)
    return sorted(classes)


def camel_case_tokens(text):
    """Split camelCase/snake_case identifiers into lowercase non-keyword tokens."""
    tokens = []
    for match in _WORD_RE.findall(text or ""):
        low = match.lower()
        if low not in _JAVA_NOISE:
            tokens.append(low)
    return tokens


def build_structural_matrix(dataset, classes):
    """N x N directed dependency matrix summed from dataset.json["edges"] (no self-loops)."""
    import numpy as np

    index = {cls: idx for idx, cls in enumerate(classes)}
    n = len(classes)
    calls = np.zeros((n, n), dtype=float)
    edge_count = 0
    for edge in dataset.get("edges", []):
        src = edge.get("src")
        dst = edge.get("dst")
        if src in index and dst in index and src != dst:
            calls[index[src], index[dst]] += float(edge.get("weight", 1.0))
            edge_count += 1
    return calls, edge_count


def _resolve_source_dir(dataset, dataset_dir):
    source_path = dataset.get("source_path")
    if not source_path:
        return None
    if os.path.isabs(source_path):
        return source_path
    return os.path.abspath(os.path.join(dataset_dir, source_path))


def _resolve_method_file(file_path, source_dir, dataset_dir):
    if not file_path:
        return None
    candidates = []
    if os.path.isabs(file_path):
        candidates.append(file_path)
    else:
        if source_dir:
            candidates.append(os.path.join(source_dir, file_path))
        candidates.append(os.path.join(dataset_dir, file_path))
    for cand in candidates:
        if os.path.isfile(cand):
            return cand
    return None


def _index_java_files(source_dir):
    if not source_dir or not os.path.isdir(source_dir):
        return []
    java_files = []
    for root, _, files in os.walk(source_dir):
        for fname in sorted(files):
            if fname.endswith(".java"):
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, source_dir).replace(os.sep, "/")
                java_files.append((rel, full))
    return java_files


def _find_by_class_name(cls, indexed_files):
    if not indexed_files:
        return None
    parts = cls.split(".")
    # Try full FQN and outer-class prefixes (e.g. pkg.Outer.Inner -> pkg/Outer.java)
    for end in range(len(parts), 0, -1):
        suffix = "/".join(parts[:end]) + ".java"
        for rel, full in indexed_files:
            if rel == suffix or rel.endswith("/" + suffix):
                return full
    return None


def resolve_class_sources(dataset, dataset_dir, classes):
    """Map each class FQN to a readable .java path (if available) and grouped method metadata."""
    source_dir = _resolve_source_dir(dataset, dataset_dir)
    methods_by_class = defaultdict(list)
    class_files = {}

    for mid, mdata in dataset.get("methods", {}).items():
        if "." not in mid:
            continue
        cls = mid.rsplit(".", 1)[0]
        methods_by_class[cls].append(mdata)
        if cls not in class_files:
            resolved = _resolve_method_file(mdata.get("file_path"), source_dir, dataset_dir)
            if resolved:
                class_files[cls] = resolved

    missing = [cls for cls in classes if cls not in class_files]
    if missing and source_dir and os.path.isdir(source_dir):
        indexed = _index_java_files(source_dir)
        for cls in missing:
            found = _find_by_class_name(cls, indexed)
            if found:
                class_files[cls] = found

    return class_files, methods_by_class


def _class_fallback_document(cls, methods):
    tokens = camel_case_tokens(cls.rsplit(".", 1)[-1])
    for m in methods:
        mname = m.get("method_name", "")
        if mname and mname != "<init>":
            tokens.extend(camel_case_tokens(mname))
        ret = m.get("return_type", "")
        if ret:
            tokens.extend(camel_case_tokens(ret.rsplit(".", 1)[-1]))
        for param in m.get("parameters", []):
            tokens.extend(camel_case_tokens(str(param).rsplit(".", 1)[-1]))
    return " ".join(tokens)


def build_semantic_matrix(dataset, dataset_dir, classes):
    """Build N x M TF-IDF matrix from Java source files, falling back to dataset.json metadata."""
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer

    class_files, methods_by_class = resolve_class_sources(dataset, dataset_dir, classes)
    docs = []
    file_cache = {}
    java_resolved = 0
    fallback_count = 0

    for cls in classes:
        fpath = class_files.get(cls)
        doc = ""
        if fpath:
            if fpath not in file_cache:
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        raw = _PKG_IMPORT_RE.sub(" ", f.read())
                    file_cache[fpath] = " ".join(camel_case_tokens(raw))
                except OSError:
                    file_cache[fpath] = ""
            doc = file_cache[fpath]
        if doc:
            java_resolved += 1
        else:
            fallback_count += 1
            doc = _class_fallback_document(cls, methods_by_class.get(cls, ()))
        docs.append(doc)

    if not classes:
        return np.zeros((0, 0), dtype=float), {
            "java_files_resolved": 0,
            "fallback_classes": 0,
            "semantic_vocab": 0,
        }

    try:
        vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english",
            token_pattern=r"(?u)\b[a-zA-Z0-9]+\b",
        )
        tfidf = vectorizer.fit_transform(docs).toarray().astype(float)
        vocab_size = tfidf.shape[1]
    except ValueError:
        tfidf = np.zeros((len(classes), 1), dtype=float)
        vocab_size = 0

    return tfidf, {
        "java_files_resolved": java_resolved,
        "fallback_classes": fallback_count,
        "semantic_vocab": vocab_size,
    }


def build_dynamic_matrix(trace_path, classes):
    """Build M x M directed call-count matrix from fosci_trace.csv.gz filtered to dataset classes."""
    import numpy as np

    known = set(classes)
    traced_classes = set()
    edge_counts = defaultdict(float)

    opener = (lambda p: gzip.open(p, "rt", encoding="utf-8", errors="ignore", newline="")) if trace_path.endswith(".gz") \
        else (lambda p: open(p, "r", encoding="utf-8", errors="ignore", newline=""))

    with opener(trace_path) as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        c1_key = "className1" if "className1" in fields and "class1" not in fields else "class1"
        c2_key = "className2" if "className2" in fields and "class2" not in fields else "class2"
        if c1_key not in fields or c2_key not in fields:
            raise ValueError(f"Invalid trace format in {trace_path}: missing class columns")
        for row in reader:
            c1 = (row.get(c1_key) or "").strip()
            c2 = (row.get(c2_key) or "").strip()
            if c1 in known:
                traced_classes.add(c1)
            if c2 in known:
                traced_classes.add(c2)
            if c1 in known and c2 in known and c1 != c2:
                edge_counts[(c1, c2)] += 1.0

    dyn_classes = sorted(traced_classes)
    if not dyn_classes:
        raise ValueError(f"Execution trace {trace_path} matched 0 classes in dataset.json")

    idx = {cls: i for i, cls in enumerate(dyn_classes)}
    dyn_calls = np.zeros((len(dyn_classes), len(dyn_classes)), dtype=float)
    for (c1, c2), cnt in edge_counts.items():
        dyn_calls[idx[c1], idx[c2]] = cnt

    return dyn_classes, dyn_calls, int(sum(edge_counts.values()))


def build_hydec_inputs(dataset, dataset_dir, out_dir, approach="hierDec", trace_path=None):
    """Write structural/, semantic/, and (for hyDec) dynamic/ files into `out_dir`."""
    import numpy as np

    classes = load_classes(dataset)
    if not classes:
        raise ValueError("dataset.json contains no classes")

    calls, edge_count = build_structural_matrix(dataset, classes)
    tfidf, sem_info = build_semantic_matrix(dataset, dataset_dir, classes)

    for sub in ("structural", "semantic"):
        sub_dir = os.path.join(out_dir, sub)
        os.makedirs(sub_dir, exist_ok=True)
        with open(os.path.join(sub_dir, "class_names.json"), "w", encoding="utf-8") as f:
            json.dump(classes, f)

    np.save(os.path.join(out_dir, "structural", "class_calls.npy"), calls)
    np.save(os.path.join(out_dir, "semantic", "class_tfidf.npy"), tfidf)

    info = {
        "classes": len(classes),
        "edges": edge_count,
        "structural_nonzero": int(np.count_nonzero(calls)),
        **sem_info,
    }

    if approach == "hyDec":
        if not trace_path or not os.path.exists(trace_path):
            raise FileNotFoundError(f"Execution trace not found: {trace_path}")
        dyn_classes, dyn_calls, dyn_events = build_dynamic_matrix(trace_path, classes)
        dyn_dir = os.path.join(out_dir, "dynamic")
        os.makedirs(dyn_dir, exist_ok=True)
        with open(os.path.join(dyn_dir, "class_names.json"), "w", encoding="utf-8") as f:
            json.dump(dyn_classes, f)
        np.save(os.path.join(dyn_dir, "class_calls.npy"), dyn_calls)
        info["dynamic_classes"] = len(dyn_classes)
        info["dynamic_calls"] = dyn_events

    return info
