"""Code2Vec AST path-context extraction and class vector embedding adapter.

Implements the canonical Al-Debagy & Martinek (2021) representation pipeline:
1. Extract AST path-contexts per Java method via `tech-srl/code2vec` JavaExtractor.
2. Encode each method into a 384-D code vector via the pretrained Code2Vec model
   (`java14m_model` or custom checkpoint) using `_calculate_weighted_contexts`.
3. Average method vectors per class; embed methodless interfaces/enums/DTOs via
   subtoken lookup in `WORDS_VOCAB` projected with `tanh([w, 0, w] @ TRANSFORM)`.
"""

import os
from pathlib import Path
import pickle
import re
import shutil
import subprocess
import tarfile
from urllib.request import urlopen

MAX_CONTEXTS = 200
MAX_PATH_LENGTH = 8
MAX_PATH_WIDTH = 2
MODEL_URL = "https://s3.amazonaws.com/code2vec/model/java14m_model.tar.gz"
DEFAULT_CACHE_ROOT = Path(__file__).resolve().parent / ".cache"
DEFAULT_MODEL_DIR = DEFAULT_CACHE_ROOT / "models" / "java14_model"
DEFAULT_CHECKPOINT_NAME = "saved_model_iter8.release"
IGNORED_SOURCE_DIRS = {".git", "target", "build", "node_modules", "test", "tests"}


def java_string_hashcode(s):
    """Imitate Java's String.hashCode() to match Code2Vec hashed path vocabularies."""
    h = 0
    for c in s:
        h = (31 * h + ord(c)) & 0xFFFFFFFF
    return str(((h + 0x80000000) & 0xFFFFFFFF) - 0x80000000)


def normalize_identifier(name):
    """Normalize a Java identifier the same way Code2Vec's Common.normalizeName does."""
    lowered = re.sub(r"[^a-zA-Z]", "", name).lower()
    return lowered or name.lower()


def split_subtokens(name):
    """Split camelCase/snake_case Java identifier into normalized Code2Vec subtokens."""
    parts = re.split(r"(?<=[a-z])(?=[A-Z])|_|[0-9]|(?<=[A-Z])(?=[A-Z][a-z])|\s+", name.strip())
    tokens = []
    for part in parts:
        cleaned = re.sub(r"[^a-zA-Z]", "", part).lower()
        if cleaned:
            tokens.append(cleaned)
    return tokens


def _find_checkpoint_in_dir(model_dir):
    """Locate a TF checkpoint prefix and vocabulary file inside `model_dir`."""
    candidates = [model_dir, model_dir / "models" / "java14_model"]
    for base in candidates:
        if not base.is_dir():
            continue
        preferred = base / DEFAULT_CHECKPOINT_NAME
        if (base / f"{DEFAULT_CHECKPOINT_NAME}.index").is_file():
            ckpt = preferred
        else:
            indexes = sorted(base.glob("*.index"))
            if not indexes:
                continue
            ckpt = indexes[0].with_suffix("")
        dict_file = _find_dict_for_checkpoint(ckpt)
        if dict_file is not None:
            return str(ckpt), str(dict_file)
    return None


def _find_dict_for_checkpoint(ckpt_prefix):
    ckpt_path = Path(ckpt_prefix)
    for candidate in (
        ckpt_path.parent / f"{ckpt_path.name}.dict",
        ckpt_path.parent / "dictionaries.bin",
    ):
        if candidate.is_file():
            return candidate
    return None


def resolve_model_files(model_path=None, cache_dir=None):
    """Resolve (checkpoint_prefix, dict_path), downloading java14m_model if needed."""
    if model_path:
        path = Path(model_path).expanduser().resolve()
        if path.is_dir():
            found = _find_checkpoint_in_dir(path)
            if found:
                return found
            raise FileNotFoundError(f"No Code2Vec checkpoint and dictionary found in directory: {path}")
        if path.name.endswith(".index"):
            path = path.with_suffix("")
        if not Path(f"{path}.index").is_file():
            raise FileNotFoundError(f"Code2Vec checkpoint index not found: {path}.index")
        dict_file = _find_dict_for_checkpoint(path)
        if dict_file is None:
            raise FileNotFoundError(f"Code2Vec dictionary (.dict or dictionaries.bin) not found near: {path}")
        return str(path), str(dict_file)

    target_dir = Path(cache_dir).resolve() if cache_dir else DEFAULT_MODEL_DIR
    found = _find_checkpoint_in_dir(target_dir)
    if found:
        return found

    download_and_extract_model(target_dir)
    found = _find_checkpoint_in_dir(target_dir)
    if not found:
        raise FileNotFoundError(f"Downloaded Code2Vec archive did not produce checkpoint files in {target_dir}")
    return found


def download_and_extract_model(target_dir, url=MODEL_URL):
    """Download and extract the official released Code2Vec java14m model into `target_dir`."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    tar_tmp = target_dir / "java14m_model.tar.gz.part"
    extract_tmp = target_dir / "_extract_tmp"
    print(f"Downloading Code2Vec pretrained model from {url} ...", flush=True)
    try:
        with urlopen(url, timeout=600) as resp, tar_tmp.open("wb") as out:
            shutil.copyfileobj(resp, out, length=1024 * 1024)
        shutil.rmtree(extract_tmp, ignore_errors=True)
        extract_tmp.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar_tmp, "r:gz") as tf_arc:
            try:
                tf_arc.extractall(extract_tmp, filter="data")
            except TypeError:
                tf_arc.extractall(extract_tmp)
        src_dir = extract_tmp / "models" / "java14_model"
        if not src_dir.is_dir():
            # Fallback: find folder containing *.index
            matches = list(extract_tmp.rglob("*.index"))
            if not matches:
                raise FileNotFoundError("Archive contains no TensorFlow checkpoint .index file")
            src_dir = matches[0].parent
        for item in src_dir.iterdir():
            dest = target_dir / item.name
            if dest.exists():
                if dest.is_dir():
                    shutil.rmtree(dest)
                else:
                    dest.unlink()
            shutil.move(str(item), str(dest))
    finally:
        tar_tmp.unlink(missing_ok=True)
        shutil.rmtree(extract_tmp, ignore_errors=True)


def _load_single_vocab(stream):
    word_to_index = pickle.load(stream)
    index_to_word = pickle.load(stream)
    _size = pickle.load(stream)
    min_idx = min(index_to_word.keys()) if index_to_word else 1
    if min_idx <= 1:
        pad_idx, oov_idx = 0, 0
    else:
        pad_idx, oov_idx = 0, 1
    return word_to_index, pad_idx, oov_idx


def load_code2vec_model(ckpt_prefix, dict_path):
    """Lazily load Code2Vec vocabularies and checkpoint weights into numpy arrays."""
    import numpy as np
    import tensorflow as tf

    with open(dict_path, "rb") as f:
        token_w2i, token_pad, token_oov = _load_single_vocab(f)
        _target_vocab = _load_single_vocab(f)
        path_w2i, path_pad, path_oov = _load_single_vocab(f)

    ckpt = tf.train.load_checkpoint(ckpt_prefix)
    return {
        "token_w2i": token_w2i,
        "token_pad_idx": token_pad,
        "token_oov_idx": token_oov,
        "path_w2i": path_w2i,
        "path_pad_idx": path_pad,
        "path_oov_idx": path_oov,
        "words_vocab": np.asarray(ckpt.get_tensor("model/WORDS_VOCAB"), dtype=np.float32),
        "paths_vocab": np.asarray(ckpt.get_tensor("model/PATHS_VOCAB"), dtype=np.float32),
        "transform": np.asarray(ckpt.get_tensor("model/TRANSFORM"), dtype=np.float32),
        "attention": np.asarray(ckpt.get_tensor("model/ATTENTION"), dtype=np.float32),
    }


def _find_java_source_roots(repo_dir):
    repo_dir = Path(repo_dir).resolve()
    if not repo_dir.is_dir():
        return []
    roots = sorted(
        p for p in repo_dir.rglob("java")
        if p.is_dir()
        and p.parts[-3:] == ("src", "main", "java")
        and not IGNORED_SOURCE_DIRS.intersection(p.relative_to(repo_dir).parts[:-3])
    )
    if roots:
        return roots
    src_dir = repo_dir / "src"
    return [src_dir] if src_dir.is_dir() else [repo_dir]


def resolve_source_root(dataset, dataset_dir):
    """Resolve `dataset['source_path']` relative to `dataset_dir` when needed."""
    src = dataset.get("source_path")
    if not src:
        return None
    p = Path(src)
    if not p.is_absolute():
        p = (Path(dataset_dir) / p).resolve()
    return p if p.exists() else None


def resolve_class_files(dataset, dataset_dir, classes):
    """Map each class FQN to its .java file path and normalized method names."""
    source_root = resolve_source_root(dataset, dataset_dir)
    ds_root = Path(dataset_dir).resolve()
    class_to_file = {}
    class_method_names = {cls: set() for cls in classes}
    class_raw_methods = {cls: set() for cls in classes}

    for mid, minfo in dataset.get("methods", {}).items():
        cls = mid.rsplit(".", 1)[0]
        if cls not in class_method_names:
            continue
        mname = minfo.get("method_name") or mid.rsplit(".", 1)[-1]
        if mname != "<init>":
            class_method_names[cls].add(normalize_identifier(mname))
            class_raw_methods[cls].add(mname)
        if cls not in class_to_file and minfo.get("file_path"):
            fp = Path(minfo["file_path"])
            candidates = [fp] if fp.is_absolute() else (
                ([source_root / fp] if source_root else []) + [ds_root / fp]
            )
            for cand in candidates:
                if cand.is_file():
                    class_to_file[cls] = cand.resolve()
                    break

    missing = [c for c in classes if c not in class_to_file]
    if missing and source_root is not None:
        roots = _find_java_source_roots(source_root)
        rel_index = {}
        for root in roots:
            for jpath in sorted(root.rglob("*.java")):
                rel = jpath.relative_to(root).as_posix()
                rel_index.setdefault(rel, jpath.resolve())
        for cls in missing:
            parts = cls.split(".")
            for cut in range(len(parts), 0, -1):
                rel_cand = "/".join(parts[:cut]) + ".java"
                if rel_cand in rel_index:
                    class_to_file[cls] = rel_index[rel_cand]
                    break

    file_to_classes = {}
    for cls, fpath in class_to_file.items():
        file_to_classes.setdefault(fpath, []).append(cls)
    return class_to_file, file_to_classes, class_method_names, class_raw_methods


def run_java_extractor(jar_path, java_file, max_path_length=MAX_PATH_LENGTH, max_path_width=MAX_PATH_WIDTH):
    """Invoke JavaExtractor.App on a single .java file and return extracted method lines."""
    cmd = [
        "java", "-cp", str(jar_path), "JavaExtractor.App",
        "--max_path_length", str(max_path_length),
        "--max_path_width", str(max_path_width),
        "--file", str(java_file),
        "--no_hash",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"JavaExtractor failed on {java_file} (exit {proc.returncode}): {proc.stderr.strip()}")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _attribute_lines_to_classes(lines, file_classes, class_method_names):
    """Assign extracted method lines from one .java file to the owning class(es)."""
    assigned = {cls: [] for cls in file_classes}
    if not lines:
        return assigned
    if len(file_classes) == 1:
        assigned[file_classes[0]] = list(lines)
        return assigned

    has_any_metadata = any(class_method_names.get(cls) for cls in file_classes)
    if not has_any_metadata:
        primary = min(file_classes, key=lambda c: (c.count("."), len(c)))
        assigned[primary] = list(lines)
        return assigned

    for line in lines:
        raw_method = line.split(" ", 1)[0]
        norm_method = normalize_identifier(raw_method.replace("|", ""))
        matches = [cls for cls in file_classes if norm_method in class_method_names.get(cls, ())]
        if matches:
            for cls in matches:
                assigned[cls].append(line)
    return assigned


def _encode_method_line(line, model, max_contexts=MAX_CONTEXTS):
    import numpy as np

    parts = line.rstrip().split(" ")
    contexts = parts[1:][:max_contexts]
    src_idx = np.full(max_contexts, model["token_pad_idx"], dtype=np.int32)
    path_idx = np.full(max_contexts, model["path_pad_idx"], dtype=np.int32)
    dst_idx = np.full(max_contexts, model["token_pad_idx"], dtype=np.int32)
    valid_mask = np.zeros(max_contexts, dtype=np.float32)

    tok_w2i = model["token_w2i"]
    path_w2i = model["path_w2i"]
    tok_oov = model["token_oov_idx"]
    path_oov = model["path_oov_idx"]
    tok_pad = model["token_pad_idx"]
    path_pad = model["path_pad_idx"]

    n_parsed = 0
    for i, ctx in enumerate(contexts):
        fields = ctx.split(",")
        if len(fields) != 3:
            continue
        w1, raw_path, w2 = fields
        s_i = tok_w2i.get(w1, tok_oov)
        p_i = path_w2i.get(java_string_hashcode(raw_path), path_oov)
        d_i = tok_w2i.get(w2, tok_oov)
        src_idx[n_parsed] = s_i
        path_idx[n_parsed] = p_i
        dst_idx[n_parsed] = d_i
        if s_i != tok_pad or d_i != tok_pad or p_i != path_pad:
            valid_mask[n_parsed] = 1.0
        n_parsed += 1

    if n_parsed > 0 and not np.any(valid_mask > 0):
        # All extracted contexts were OOV; unmask parsed slots to avoid softmax(-inf) NaNs.
        valid_mask[:n_parsed] = 1.0
    return src_idx, path_idx, dst_idx, valid_mask, n_parsed


def embed_method_lines(lines, model, max_contexts=MAX_CONTEXTS):
    """Compute Code2Vec 384-D method vectors matching `tensorflow_model.py:236-263`."""
    import numpy as np

    encoded = [_encode_method_line(line, model, max_contexts=max_contexts) for line in lines]
    encoded = [e for e in encoded if e[4] > 0]
    if not encoded:
        dim = model["transform"].shape[1]
        return np.zeros((0, dim), dtype=np.float32)

    src_batch = np.stack([e[0] for e in encoded], axis=0)
    path_batch = np.stack([e[1] for e in encoded], axis=0)
    dst_batch = np.stack([e[2] for e in encoded], axis=0)
    mask_batch = np.stack([e[3] for e in encoded], axis=0)

    src_emb = model["words_vocab"][src_batch]
    path_emb = model["paths_vocab"][path_batch]
    dst_emb = model["words_vocab"][dst_batch]
    context_emb = np.concatenate([src_emb, path_emb, dst_emb], axis=-1)

    flat_emb = np.tanh(context_emb @ model["transform"])
    logits = (flat_emb @ model["attention"]).squeeze(-1)
    logits = logits + np.where(mask_batch > 0, 0.0, -np.inf)
    logits = logits - np.max(logits, axis=1, keepdims=True)
    exp_logits = np.exp(logits)
    attn = (exp_logits / np.sum(exp_logits, axis=1, keepdims=True))[:, :, None]
    return np.sum(flat_emb * attn, axis=1).astype(np.float32)


def embed_methodless_class(class_fqn, method_names, model):
    """Fallback embedding for methodless interfaces/enums/DTOs via WORDS_VOCAB + TRANSFORM."""
    import numpy as np

    simple_name = class_fqn.rsplit(".", 1)[-1]
    candidates = [normalize_identifier(simple_name)] + split_subtokens(simple_name)
    for mname in sorted(method_names):
        candidates.append(normalize_identifier(mname))
        candidates.extend(split_subtokens(mname))

    tok_w2i = model["token_w2i"]
    indices = [tok_w2i[tok] for tok in candidates if tok in tok_w2i]
    if not indices:
        indices = [model["token_pad_idx"]]

    word_vecs = model["words_vocab"][np.array(indices, dtype=np.int32)]
    zeros = np.zeros((len(indices), model["paths_vocab"].shape[1]), dtype=np.float32)
    contexts = np.concatenate([word_vecs, zeros, word_vecs], axis=-1)
    transformed = np.tanh(contexts @ model["transform"])
    return np.mean(transformed, axis=0).astype(np.float32)


def build_class_embeddings(dataset, dataset_dir, classes, jar_path, model):
    """Extract Java AST path-contexts and build (N, D) class vectors for all `classes`."""
    import numpy as np

    class_to_file, file_to_classes, class_method_names, class_raw_methods = resolve_class_files(
        dataset, dataset_dir, classes
    )
    class_lines = {cls: [] for cls in classes}
    extracted_files = 0
    for java_file, fclasses in sorted(file_to_classes.items(), key=lambda item: str(item[0])):
        lines = run_java_extractor(jar_path, str(java_file))
        extracted_files += 1
        attributed = _attribute_lines_to_classes(lines, fclasses, class_method_names)
        for cls, cls_lines in attributed.items():
            class_lines[cls].extend(cls_lines)

    vectors = []
    classes_with_methods = 0
    methodless_classes = 0
    total_methods_embedded = 0

    for cls in classes:
        lines = class_lines[cls]
        if lines:
            mvecs = embed_method_lines(lines, model, max_contexts=MAX_CONTEXTS)
            if len(mvecs) > 0:
                vectors.append(np.mean(mvecs, axis=0))
                classes_with_methods += 1
                total_methods_embedded += len(mvecs)
                continue
        vectors.append(embed_methodless_class(cls, class_raw_methods.get(cls, set()), model))
        methodless_classes += 1

    matrix = np.vstack(vectors).astype(np.float32)
    stats = {
        "files_extracted": extracted_files,
        "classes_with_methods": classes_with_methods,
        "methodless_fallback_classes": methodless_classes,
        "total_methods_embedded": total_methods_embedded,
    }
    return matrix, stats
