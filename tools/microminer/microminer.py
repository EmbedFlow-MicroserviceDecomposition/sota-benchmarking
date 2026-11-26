"""Canonical MicroMiner 3-phase decomposition engine (Trabelsi et al., JSEP 2023).

Reconstructed directly from the authors' 3 replication notebooks in ``originals/``:
- Phase 1 (``createEmbad.ipynb`` + ``classificationML-Compiere.ipynb``): CodeBERT
  (510-token chunked ``[CLS]`` mean pooling) or TF-IDF fallback + Linear SVM
  (``SVC(kernel="linear", C=2)`` on a 30/70 split) to type classes into
  ``application``, ``entity``, and ``utility``.
- Phase 2 (``microMiner.ipynb`` cells 17-22): Weighted undirected Louvain
  community detection per layer (``resolution=0.5``) + singleton refinement
  ``fineTuneCluster`` on ``entity`` and ``application`` layers.
- Phase 3 (``microMiner.ipynb`` cells 7-13 & 23-31): Source tokenization, exact
  stopword filtering, camelCase splitting, WordNet lemmatization, Word2Vec
  embeddings (word-count-weighted per typed service), Floyd-Warshall static
  distances (``INF = 999.0``, ``100.0 / dis``) + ``2.0 * cosine_distance``, and
  Fuzzy C-Means (``m = 3``) centered on Application services.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import networkx as nx
import numpy as np
from scipy.sparse.csgraph import floyd_warshall
from scipy.spatial.distance import cosine as cosine_distance
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split
from sklearn.svm import SVC

# Table 1 static relationship weights (Trabelsi et al., JSEP 2023).
WEIGHTS: Dict[str, float] = {
    "EXTENDS": 100.0,
    "IMPLEMENTS": 100.0,
    "FIELD": 100.0,
    "ASSOCIATION": 25.0,
    "INSTANTIATION": 25.0,
    "CALL": 5.0,
}

# Exact JavaFX-POS seed sets from originals/microMiner.ipynb:98-100.
AUTHORS_ENTITY_SEEDS: Set[str] = {
    "employeemodel", "invoicemodel", "saledao", "purchasemodel", "productmodel",
    "productdao", "categorymodel", "invoicedao", "product", "purchase", "sale",
    "employeedao", "employee", "salesmodel", "supplier", "categorydao",
    "suppliermodel", "purchasedao", "item", "supplierdao", "invoice", "payment",
}
AUTHORS_APP_SEEDS: Set[str] = {
    "saleinterface", "employeeinterface", "suppliercontroller", "supplieraddcontroller",
    "reportviewcontroller", "employeecontroller", "categoryaddcontroller", "mainapp",
    "confirmcontroller", "productaddcontroller", "categoryinterface", "category",
    "printinvoice", "categorycontroller", "productinterface", "poscontroller",
    "suppliereditcontroller", "logincontroller", "employeeaddcontroller",
    "purchaseinterface", "invoicecontroller", "reportcontroller", "purchaseaddcontroller",
    "categoryeditcontroller", "purchasecontroller", "supplierinterface",
    "employeeeditcontroller", "productcontroller", "salescontroller",
    "reportinterface", "admincontroller", "producteditcontroller",
}
AUTHORS_UTILITY_SEEDS: Set[str] = {"hibernateutil"}

# Exact stopword list from originals/microMiner.ipynb:181 (preserving "is"/"value" and "isvalue").
STOP_WORDS: Set[str] = {
    "handle", "cancel", "title", "parent", "cell", "bean", "loader", "stage",
    "pressed", "dragged", "view", "box", "initialize", "total", "image", "icon",
    "offset", "node", "scene", "duration", "drawer", "nav", "load", "data",
    "is", "empty", "all", "static", "cascade", "transaction", "override", "join",
    "one", "description", "strategy", "generation", "persistence", "generated",
    "io", "projection", "property", "commit", "dao", "this", "style", "menu",
    "begin", "column", "translate", "on", "selected", "name", "png", "logo",
    "string", "table", "exception", "contains", "filter", "controller",
    "implement", "button", "session", "hibernate", "array", "org", "save",
    "clear", "boolean", "init", "remove", "entity", "observable", "double",
    "length", "alert", "action", "field", "bundle", "show", "root", "list",
    "index", "text", "return", "wait", "lower", "true", "false", "java",
    "util", "long", "collection", "interface", "layout", "value", "valid",
    "isvalue", "type", "model", "public", "private", "id", "error", "void",
    "not", "int", "float", "for", "set", "catch", "try", "javafx", "import",
    "class", "com", "package", "if", "else", "null", "no", "delete", "add",
    "edit", "get", "new", "open", "close", "mouse", "event", "window", "throw",
}

UTILITY_NAME_TOKENS: Set[str] = {
    "util", "utils", "config", "configuration", "security", "helper", "helpers",
    "filter", "exception", "common", "constant", "constants", "enum", "enums",
    "base", "abstract", "context", "factory", "manager", "wrapper", "swagger",
    "converter", "loader", "cache",
}
UTILITY_PKG_SEGMENTS: Set[str] = {
    "util", "utils", "config", "configuration", "security", "common",
    "helper", "helpers", "exception", "exceptions", "enums", "cache",
    "converter", "swagger",
}

ENTITY_ROLE_TOKENS: Set[str] = {
    "entity", "entities", "model", "models", "dao", "repository", "mapper",
    "dto", "domain", "pojo", "record", "vo", "po", "table", "pk",
}
ENTITY_DOMAIN_TOKENS: Set[str] = {
    "bean", "item", "user", "role", "account", "order", "product", "category",
    "customer", "flight", "booking", "payment", "invoice", "supplier",
    "employee", "sale", "purchase",
}
ENTITY_NAME_TOKENS: Set[str] = ENTITY_ROLE_TOKENS | ENTITY_DOMAIN_TOKENS
ENTITY_PKG_SEGMENTS: Set[str] = {
    "domain", "model", "models", "entity", "entities", "dao", "repository",
    "repositories", "mapper", "dto", "db", "pojos", "beans", "jpa",
}

APP_NAME_TOKENS: Set[str] = {
    "controller", "action", "actionbean", "resource", "endpoint", "view",
    "page", "servlet", "handler", "ui", "interface", "process", "rest",
    "app", "mainapp", "service", "impl",
}
APP_PKG_SEGMENTS: Set[str] = {
    "controller", "controllers", "web", "api", "rest", "action", "actions",
    "ui", "view", "views", "servlet", "servlets", "service", "services",
    "business", "war",
}

CACHE_ROOT = Path(__file__).resolve().parent / ".cache"
DEFAULT_INF = 999.0


def extract_classes(dataset: Dict[str, Any]) -> List[str]:
    """Return sorted unique class FQNs declared in dataset.json."""
    classes: Set[str] = set(dataset.get("classes", ()))
    for method_id in dataset.get("methods", {}):
        if "." in method_id:
            classes.add(method_id.rsplit(".", 1)[0])
        else:
            classes.add(method_id)
    for edge in dataset.get("edges", []):
        classes.add(edge["src"])
        classes.add(edge["dst"])
    return sorted(c for c in classes if isinstance(c, str) and c.strip())


def _resolve_source_dir(dataset: Dict[str, Any], dataset_dir: Path) -> Optional[Path]:
    """Locate the monolith source directory if present on disk."""
    raw = dataset.get("source_path")
    candidates: List[Path] = []
    if isinstance(raw, str) and raw.strip():
        raw_path = Path(raw)
        if raw_path.is_absolute():
            candidates.append(raw_path)
        else:
            candidates.append((dataset_dir / raw_path).resolve())
            if raw_path.parts and raw_path.parts[0] not in (".", ".."):
                repo_root = Path(__file__).resolve().parents[2]
                candidates.append((repo_root / raw_path).resolve())
    candidates.append(dataset_dir.resolve())
    for cand in candidates:
        if cand.is_dir() and any(cand.rglob("*.java")):
            return cand
    return None


def _index_java_files(source_dir: Optional[Path]) -> Tuple[Dict[str, Path], Dict[str, List[Path]]]:
    """Index .java files by normalized POSIX suffix and lowercase basename."""
    by_rel_posix: Dict[str, Path] = {}
    by_stem: Dict[str, List[Path]] = {}
    if source_dir is None or not source_dir.is_dir():
        return by_rel_posix, by_stem

    ignored = {".git", "target", "build", "node_modules"}
    all_java = []
    for path in sorted(source_dir.rglob("*.java")):
        rel_parts = path.relative_to(source_dir).parts
        if ignored.intersection(rel_parts):
            continue
        all_java.append(path)

    # Prefer main production files over test files when basenames collide.
    all_java.sort(key=lambda p: ("/src/test/" in p.as_posix(), len(p.parts), p.as_posix()))
    for path in all_java:
        posix = path.relative_to(source_dir).as_posix()
        by_rel_posix[posix] = path
        by_stem.setdefault(path.stem.lower(), []).append(path)
    return by_rel_posix, by_stem


def _resolve_method_file(
    raw_fp: str, dataset_dir: Path, source_dir: Optional[Path]
) -> Optional[Path]:
    """Resolve a file_path field from dataset.json['methods']."""
    if not raw_fp:
        return None
    fp = Path(raw_fp)
    candidates = [fp] if fp.is_absolute() else [dataset_dir / fp]
    if not fp.is_absolute():
        if source_dir is not None:
            candidates.append(source_dir / fp)
        candidates.append(Path(__file__).resolve().parents[2] / fp)
    for cand in candidates:
        if cand.is_file():
            return cand.resolve()
    return None


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1", errors="replace")


def resolve_java_texts(
    dataset: Dict[str, Any], dataset_dir: Path, classes: Sequence[str]
) -> Tuple[Dict[str, str], int, int]:
    """Resolve .java source texts for classes when available on disk."""
    source_dir = _resolve_source_dir(dataset, dataset_dir)
    method_paths: Dict[str, str] = {}
    for mid, meta in dataset.get("methods", {}).items():
        if isinstance(meta, dict) and meta.get("file_path"):
            cls = mid.rsplit(".", 1)[0] if "." in mid else mid
            method_paths.setdefault(cls, str(meta["file_path"]))

    by_rel_posix, by_stem = _index_java_files(source_dir)
    java_texts: Dict[str, str] = {}
    resolved = 0
    missing = 0

    for cls in classes:
        path: Optional[Path] = None
        if cls in method_paths:
            path = _resolve_method_file(method_paths[cls], dataset_dir, source_dir)

        if path is None and by_rel_posix:
            parts = cls.split(".")
            for end in range(len(parts), 0, -1):
                suffix = "/".join(parts[:end]) + ".java"
                matches = [p for rel, p in by_rel_posix.items() if rel == suffix or rel.endswith("/" + suffix)]
                if matches:
                    path = matches[0]
                    break

        if path is None and by_stem:
            parts = cls.split(".")
            for end in range(len(parts), 0, -1):
                hits = by_stem.get(parts[end - 1].lower(), [])
                if len(hits) == 1:
                    path = hits[0]
                    break

        if path is not None and path.is_file():
            java_texts[cls] = _read_text_safe(path)
            resolved += 1
        else:
            missing += 1

    return java_texts, resolved, missing


def _synthetic_class_text(cls: str, methods: Dict[str, Any]) -> str:
    """Fallback text representation from FQN + method metadata when .java files are absent."""
    parts = [cls.replace(".", " ")]
    prefix = cls + "."
    for mid, meta in methods.items():
        if not mid.startswith(prefix):
            continue
        if isinstance(meta, dict):
            parts.append(str(meta.get("method_name", "")))
            parts.append(str(meta.get("return_type", "")))
            parts.extend(str(p) for p in meta.get("parameters", []))
            parts.extend(str(c) for c in meta.get("calls", []))
    return " ".join(p for p in parts if p)


def _split_camel(text: str) -> List[str]:
    """Split camelCase/PascalCase tokens using the notebook's '.[^A-Z]*' rule."""
    if not text:
        return []
    return re.findall(r".[^A-Z]*", text)


def _simple_lemmatize(word: str) -> str:
    """Deterministic lightweight fallback lemmatizer when NLTK WordNet is absent."""
    w = word.lower()
    if len(w) <= 3:
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "xes", "zes")) and len(w) > 4:
        return w[:-2]
    if w.endswith("sses") and len(w) > 5:
        return w[:-2]
    if w.endswith("s") and not w.endswith(("ss", "us", "is")):
        return w[:-1]
    return w


def _get_lemmatizer() -> Callable[[str], str]:
    """Lazily load NLTK WordNetLemmatizer if available, else return deterministic fallback."""
    try:
        import nltk
        from nltk.stem import WordNetLemmatizer

        # NLTK refuses directories under world-writable ancestors such as /tmp; use ~/nltk_data unless NLTK_DATA is set.
        nltk_dir = Path(os.environ.get("NLTK_DATA") or (Path.home() / "nltk_data"))
        if nltk_dir.is_dir() and str(nltk_dir) not in nltk.data.path:
            nltk.data.path.insert(0, str(nltk_dir))
        lem = WordNetLemmatizer()
        try:
            lem.lemmatize("classes")
            return lem.lemmatize
        except LookupError:
            nltk_dir.mkdir(parents=True, exist_ok=True)
            if nltk.download("wordnet", download_dir=str(nltk_dir), quiet=True):
                if str(nltk_dir) not in nltk.data.path:
                    nltk.data.path.insert(0, str(nltk_dir))
                lem.lemmatize("classes")
                return lem.lemmatize
    except Exception:
        pass
    return _simple_lemmatize


def tokenize_class_source(
    text: str, lemmatize: Callable[[str], str]
) -> List[str]:
    """Tokenize source text following originals/microMiner.ipynb:197-214."""
    raw_words: List[str] = []
    for line in text.splitlines():
        sentence = " ".join(re.findall(r"[a-zA-Z]+", line))
        for w in sentence.split():
            if w not in STOP_WORDS and w.lower() not in STOP_WORDS:
                raw_words.append(w)

    pieces: List[str] = []
    for w in raw_words:
        pieces.extend(_split_camel(w))

    kept: List[str] = []
    for piece in pieces:
        t = lemmatize(piece.lower())
        if len(t) > 1 and t not in STOP_WORDS:
            kept.append(t)
    return kept


def derive_seed_label(fqn: str) -> str:
    """Derive Phase 1 seed label ('application', 'entity', 'utility').

    Uses the authors' exact JavaFX-POS seed sets when matched (microMiner.ipynb:98-100),
    and dot-separated package segments (walking leaf-to-root, never raw substring
    matching so 'websphere'/'weblogger' never trigger 'web') plus camelCase tokens.
    """
    simple = fqn.split(".")[-1]
    simple_lower = simple.lower()
    pkg_list = fqn.lower().split(".")[:-1]
    pkg_segments = set(pkg_list)
    name_tokens = {w.lower() for w in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", simple)}

    # 1. Exact authors' JavaFX-POS seeds.
    if simple_lower in AUTHORS_UTILITY_SEEDS:
        return "utility"
    if simple_lower in AUTHORS_ENTITY_SEEDS:
        return "entity"
    if simple_lower in AUTHORS_APP_SEEDS and not (pkg_segments & {"entity", "entities", "model", "models"}):
        return "application"

    # 2. Architectural role patterns before generic domain nouns (so OrderService/AccountActionBean are application, not entity).
    if name_tokens & UTILITY_NAME_TOKENS or any(
        k in simple_lower for k in ("util", "config", "security", "helper", "filter", "exception", "converter", "swagger")
    ):
        return "utility"
    if name_tokens & ENTITY_ROLE_TOKENS or any(
        k in simple_lower for k in ("entity", "model", "dao", "repository", "mapper", "dto", "domain", "pojo")
    ):
        return "entity"
    if "impl" in simple_lower and (pkg_segments & ENTITY_PKG_SEGMENTS):
        return "entity"
    if name_tokens & APP_NAME_TOKENS or any(
        k in simple_lower for k in ("controller", "servlet", "endpoint", "handler", "action", "resource", "service", "impl")
    ):
        return "application"
    if name_tokens & ENTITY_DOMAIN_TOKENS:
        return "entity"

    # 3. Dot-separated package segments ordered leaf-to-root so subpackages win over root org names (e.g. com.upachar.web.common.dto).
    for seg in reversed(pkg_list):
        if seg in ENTITY_PKG_SEGMENTS:
            return "entity"
        if seg in UTILITY_PKG_SEGMENTS:
            return "utility"
        if seg in APP_PKG_SEGMENTS:
            return "application"

    return "entity"


def embed_codebert(
    classes: Sequence[str],
    java_texts: Dict[str, str],
    methods: Dict[str, Any],
    cache_dir: Optional[Path] = None,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Phase 1 CodeBERT embedding: 510-token chunked [CLS] mean pooling (createEmbad.ipynb)."""
    import torch
    from transformers import AutoModel, AutoTokenizer

    resolved_cache = os.environ.get("HF_HOME") or str(cache_dir or (CACHE_ROOT / "huggingface"))
    Path(resolved_cache).mkdir(parents=True, exist_ok=True)
    tokenizer = AutoTokenizer.from_pretrained("microsoft/codebert-base", cache_dir=resolved_cache)
    model = AutoModel.from_pretrained("microsoft/codebert-base", cache_dir=resolved_cache)

    device_name = "cpu"
    try:
        if torch.cuda.is_available():
            model = model.to("cuda")
            device_name = "cuda"
    except Exception:
        model = model.to("cpu")
        device_name = "cpu"
    model.eval()

    vectors: List[np.ndarray] = []
    with torch.inference_mode():
        for cls in classes:
            text = java_texts[cls] if cls in java_texts else _synthetic_class_text(cls, methods)
            code_tokens = tokenizer.tokenize(text)
            chunk_embs: List[np.ndarray] = []
            offset = 0
            while True:
                chunk = code_tokens[offset : offset + 510]
                tokens = [tokenizer.cls_token] + chunk + [tokenizer.sep_token]
                token_ids = tokenizer.convert_tokens_to_ids(tokens)
                tensor_ids = torch.tensor(token_ids, dtype=torch.long)[None, :].to(model.device)
                context_embeddings = model(tensor_ids)[0]
                chunk_embs.append(context_embeddings[0][0].detach().cpu().numpy().astype(np.float64))
                offset += 510
                if offset >= len(code_tokens):
                    break
            vectors.append(np.mean(chunk_embs, axis=0))

    return np.vstack(vectors), {"model": "microsoft/codebert-base", "device": device_name}


def embed_tfidf(
    classes: Sequence[str],
    java_texts: Dict[str, str],
    methods: Dict[str, Any],
) -> np.ndarray:
    """Offline TF-IDF class embeddings for Phase 1 when CodeBERT/sources are unavailable."""
    docs: List[str] = []
    for cls in classes:
        src = java_texts.get(cls, "")
        meta_text = _synthetic_class_text(cls, methods)
        combined = f"{src} {meta_text}".strip() or cls
        words = re.findall(r"[A-Za-z0-9]+", combined)
        split_tokens: List[str] = []
        for w in words:
            split_tokens.extend(p.lower() for p in _split_camel(w) if len(p) > 1)
        docs.append(" ".join(split_tokens) if split_tokens else cls.lower())

    max_feat = min(768, max(64, len(classes) * 16))
    vectorizer = TfidfVectorizer(token_pattern=r"(?u)\b\w+\b", max_features=max_feat)
    try:
        mat = vectorizer.fit_transform(docs).toarray()
    except ValueError:
        mat = np.eye(len(classes), dtype=np.float64)
    return np.asarray(mat, dtype=np.float64)


def classify_layers_svm(
    classes: Sequence[str],
    features: np.ndarray,
    seed: int,
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Phase 1 Linear SVM layer classifier (classificationML-Compiere.ipynb:63-80,173-205)."""
    seed_labels = [derive_seed_label(c) for c in classes]
    n = len(classes)
    seed_counts = {lbl: seed_labels.count(lbl) for lbl in ("application", "entity", "utility")}

    if n < 4 or len(set(seed_labels)) < 2:
        final_labels = list(seed_labels)
        svm_used = False
    else:
        indices = list(range(n))
        train_idx, test_idx = train_test_split(indices, random_state=seed, test_size=0.7)

        # Ensure "utility" is in y_train if present anywhere (classificationML-Compiere.ipynb:70-79).
        if "utility" in seed_labels and not any(seed_labels[i] == "utility" for i in train_idx):
            for idx in test_idx:
                if seed_labels[idx] == "utility":
                    train_idx.append(idx)
                    if len(test_idx) > 1:
                        test_idx.remove(idx)
                    break

        # Ensure >= 2 classes in y_train so SVC can fit cleanly on small graphs.
        if len({seed_labels[i] for i in train_idx}) < 2:
            existing = seed_labels[train_idx[0]]
            for idx in test_idx:
                if seed_labels[idx] != existing:
                    train_idx.append(idx)
                    if len(test_idx) > 1:
                        test_idx.remove(idx)
                    break

        if not test_idx or len({seed_labels[i] for i in train_idx}) < 2:
            final_labels = list(seed_labels)
            svm_used = False
        else:
            y_train = [seed_labels[i] for i in train_idx]
            clf = SVC(kernel="linear", C=2, random_state=seed)
            clf.fit(features[train_idx], y_train)
            preds = clf.predict(features[test_idx])

            assigned: Dict[int, str] = {i: seed_labels[i] for i in train_idx}
            for i, pred in zip(test_idx, preds):
                assigned[i] = str(pred)
            final_labels = [assigned[i] for i in range(n)]
            svm_used = True

    layer_map = {cls: lbl for cls, lbl in zip(classes, final_labels)}
    # Guarantee at least one Application class so Phase 3 always has centroids.
    if "application" not in layer_map.values() and classes:
        app_seeded = [c for c, lbl in zip(classes, seed_labels) if lbl == "application"]
        layer_map[app_seeded[0] if app_seeded else classes[0]] = "application"

    meta = {
        "seed_counts": seed_counts,
        "svm_used": svm_used,
        "layer_counts": {lbl: sum(1 for v in layer_map.values() if v == lbl) for lbl in ("application", "entity", "utility")},
    }
    return layer_map, meta


def aggregate_edge_weights(edges: Sequence[Dict[str, Any]]) -> Dict[Tuple[str, str], float]:
    """Aggregate directed typed edges into undirected Table 1 static weights."""
    pair_weights: Dict[Tuple[str, str], float] = {}
    for edge in edges:
        src = edge.get("src", "")
        dst = edge.get("dst", "")
        if not src or not dst or src == dst:
            continue
        etype = str(edge.get("type", "CALL")).upper()
        base = WEIGHTS.get(etype, 5.0)
        raw_w = float(edge.get("weight", 1.0))
        key = (src, dst) if src < dst else (dst, src)
        pair_weights[key] = pair_weights.get(key, 0.0) + base * raw_w
    return pair_weights


def _pair_weight(pair_weights: Dict[Tuple[str, str], float], u: str, v: str) -> float:
    if u == v:
        return 0.0
    return pair_weights.get((u, v) if u < v else (v, u), 0.0)


def fine_tune_cluster(
    services: List[List[str]], pair_weights: Dict[Tuple[str, str], float]
) -> List[List[str]]:
    """Phase 2 singleton refinement (originals/microMiner.ipynb:456-513)."""
    singletons = [s[0] for s in services if len(s) < 2]
    for singleton in singletons:
        if [singleton] not in services:
            continue
        scores = []
        for s in services:
            if s == [singleton]:
                scores.append(0.0)
            else:
                scores.append(sum(_pair_weight(pair_weights, singleton, member) for member in s))
        max_score = max(scores) if scores else 0.0
        if max_score > 0.0:
            max_indices = [i for i, v in enumerate(scores) if v == max_score]
            if len(max_indices) == 1:
                services[max_indices[0]].append(singleton)
                services[max_indices[0]].sort()
                services.remove([singleton])
    return services


def identify_typed_services(
    classes_by_layer: Dict[str, List[str]],
    pair_weights: Dict[Tuple[str, str], float],
    seed: int,
) -> Dict[str, List[List[str]]]:
    """Phase 2: Louvain community detection (resolution=0.5) + fineTuneCluster."""
    typed_services: Dict[str, List[List[str]]] = {}
    for layer in ("application", "entity", "utility"):
        members = sorted(classes_by_layer.get(layer, []))
        if not members:
            typed_services[layer] = []
            continue

        g = nx.Graph()
        g.add_nodes_from(members)
        member_set = set(members)
        for (u, v), w in pair_weights.items():
            if u in member_set and v in member_set:
                g.add_edge(u, v, weight=w)

        if g.number_of_edges() == 0:
            services = [[m] for m in members]
        else:
            comms = nx.community.louvain_communities(g, weight="weight", resolution=0.5, seed=seed)
            services = sorted([sorted(c) for c in comms if c], key=lambda c: c[0])

        # fineTuneCluster is run on entity and application layers ONLY (microMiner.ipynb:490-512).
        if layer in ("entity", "application") and len(services) > 1:
            services = fine_tune_cluster(services, pair_weights)
            services.sort(key=lambda c: c[0])

        typed_services[layer] = services
    return typed_services


def _build_corpus_word2vec(token_lists: Dict[str, List[str]], dim: int = 300) -> Dict[str, np.ndarray]:
    """Fast deterministic 300-D corpus-derived embeddings without external downloads."""
    vocab = sorted({tok for toks in token_lists.values() for tok in toks})
    if not vocab:
        return {}

    idx_of = {tok: i for i, tok in enumerate(vocab)}
    n_vocab = len(vocab)
    n_docs = len(token_lists)
    cooc = np.zeros((n_vocab, n_docs), dtype=np.float64)
    for d_idx, (_, toks) in enumerate(sorted(token_lists.items())):
        for tok in toks:
            cooc[idx_of[tok], d_idx] += 1.0

    # Combine document distribution with character n-gram TF-IDF so related terms share signal.
    char_vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
    char_mat = char_vec.fit_transform(vocab).toarray()
    combined = np.hstack([cooc, char_mat])

    if combined.shape[1] >= dim and min(combined.shape) > dim:
        svd = TruncatedSVD(n_components=dim, random_state=42)
        proj = svd.fit_transform(combined)
    else:
        rng = np.random.default_rng(42)
        proj_mat = rng.normal(0.0, 1.0 / np.sqrt(dim), size=(combined.shape[1], dim))
        proj = combined @ proj_mat

    vectors: Dict[str, np.ndarray] = {}
    for tok, i in idx_of.items():
        vec = proj[i]
        norm = float(np.linalg.norm(vec))
        if norm > 0.0:
            vec = vec / norm
        else:
            digest = hashlib.sha256(tok.encode("utf-8")).digest()
            seed_val = int.from_bytes(digest[:8], "little")
            vec = np.random.default_rng(seed_val).normal(0.0, 1.0, size=dim)
            vec /= float(np.linalg.norm(vec))
        vectors[tok] = vec.astype(np.float64)
    return vectors


def _load_google_news_word2vec() -> Any:
    """Lazily load gensim word2vec-google-news-300."""
    default_user_dir = Path.home() / "gensim-data"
    if not (default_user_dir / "word2vec-google-news-300").exists():
        cache_dir = CACHE_ROOT / "gensim-data"
        cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("GENSIM_DATA_DIR", str(cache_dir))
    import gensim.downloader as api

    return api.load("word2vec-google-news-300")


def _compute_service_embeddings(
    classes: Sequence[str],
    typed_services: Dict[str, List[List[str]]],
    java_texts: Dict[str, str],
    methods: Dict[str, Any],
    w2v_model: Any,
    dim: int = 300,
) -> Tuple[List[str], Dict[str, List[str]], Dict[str, np.ndarray]]:
    """Compute class embeddings and word-count-weighted service embeddings (microMiner.ipynb:235-278,529-567)."""
    lemmatize = _get_lemmatizer()
    raw_tokens: Dict[str, List[str]] = {}
    for cls in classes:
        text = java_texts.get(cls) or _synthetic_class_text(cls, methods)
        toks = tokenize_class_source(text, lemmatize)
        if not toks:
            toks = [p.lower() for p in _split_camel(cls.split(".")[-1]) if len(p) > 1]
        raw_tokens[cls] = toks

    if w2v_model is None:
        w2v_model = _build_corpus_word2vec(raw_tokens, dim=dim)

    w_list_class: Dict[str, List[str]] = {}
    embad_dict: Dict[str, np.ndarray] = {}
    for cls in classes:
        kept = [t for t in raw_tokens[cls] if t in w2v_model]
        w_list_class[cls] = kept
        if kept:
            vecs = [np.asarray(w2v_model[t], dtype=np.float64) for t in kept]
            embad_dict[cls] = np.mean(vecs, axis=0)
        else:
            digest = hashlib.sha256(cls.encode("utf-8")).digest()
            seed_val = int.from_bytes(digest[:8], "little")
            fallback = np.random.default_rng(seed_val).normal(0.0, 1e-3, size=dim)
            embad_dict[cls] = fallback

    node_list: List[str] = []
    services: Dict[str, List[str]] = {}
    services_embad: Dict[str, np.ndarray] = {}

    prefix_map = {"application": "Application", "entity": "Entity", "utility": "utility"}
    for layer in ("application", "entity", "utility"):
        prefix = prefix_map[layer]
        for idx, members in enumerate(typed_services.get(layer, [])):
            svc_name = f"{prefix}_{idx}_{members[0]}"
            node_list.append(svc_name)
            services[svc_name] = list(members)

            total_words = 0
            weighted_sum = np.zeros(dim, dtype=np.float64)
            for c in members:
                wc = len(w_list_class[c])
                weighted_sum += embad_dict[c] * wc
                total_words += wc
            if total_words > 0:
                services_embad[svc_name] = weighted_sum / float(total_words)
            else:
                services_embad[svc_name] = np.mean([embad_dict[c] for c in members], axis=0)

    return node_list, services, services_embad


def _safe_cosine_dist(u: np.ndarray, v: np.ndarray) -> float:
    nu, nv = float(np.linalg.norm(u)), float(np.linalg.norm(v))
    if nu == 0.0 or nv == 0.0:
        return 1.0
    d = float(cosine_distance(u, v))
    if not np.isfinite(d):
        return 1.0
    return max(0.0, d)


def _select_centroids(
    node_list: Sequence[str],
    services: Dict[str, List[str]],
    distances: np.ndarray,
    app_indices: List[int],
    target_k: Optional[int],
) -> List[int]:
    """Select Application centroids (automatic K = len(app_indices) unless --k overrides)."""
    if target_k is None or target_k == len(app_indices):
        return list(app_indices)

    effective_k = max(1, min(target_k, len(node_list)))
    if effective_k < len(app_indices):
        # Greedy furthest-point sampling seeded by the largest Application service.
        first = max(app_indices, key=lambda i: (len(services[node_list[i]]), -i))
        chosen = [first]
        while len(chosen) < effective_k:
            remaining = [i for i in app_indices if i not in chosen]
            next_c = max(remaining, key=lambda r: (min(distances[r, c] for c in chosen), -r))
            chosen.append(next_c)
        return chosen

    # Augment Application centroids with furthest Entity/Utility services when --k > len(app_indices).
    chosen = list(app_indices)
    remaining = [i for i in range(len(node_list)) if i not in chosen]
    while len(chosen) < effective_k and remaining:
        next_c = max(remaining, key=lambda r: (min(distances[r, c] for c in chosen), -r))
        chosen.append(next_c)
        remaining.remove(next_c)
    return chosen


def phase3_map_services(
    classes: Sequence[str],
    typed_services: Dict[str, List[List[str]]],
    pair_weights: Dict[Tuple[str, str], float],
    java_texts: Dict[str, str],
    methods: Dict[str, Any],
    w2v_mode: str,
    target_k: Optional[int],
    soft_threshold: float,
) -> Tuple[Dict[str, int], Dict[str, Any]]:
    """Phase 3: Floyd-Warshall + cosine semantic distance + Fuzzy C-Means (m=3)."""
    w2v_model = _load_google_news_word2vec() if w2v_mode == "google-news" else None
    node_list, services, services_embad = _compute_service_embeddings(
        classes=classes,
        typed_services=typed_services,
        java_texts=java_texts,
        methods=methods,
        w2v_model=w2v_model,
    )

    n_v = len(node_list)
    if n_v == 0:
        return {c: 0 for c in classes}, {"k": 0, "above_threshold_009": {}}

    adj_matrix = np.full((n_v, n_v), DEFAULT_INF, dtype=np.float64)
    np.fill_diagonal(adj_matrix, 0.0)

    for i in range(n_v):
        members_i = services[node_list[i]]
        for j in range(i + 1, n_v):
            members_j = services[node_list[j]]
            dis = sum(
                _pair_weight(pair_weights, u, v)
                for u in members_i
                for v in members_j
            )
            if dis > 0.0:
                cost = 100.0 / dis
                adj_matrix[i, j] = cost
                adj_matrix[j, i] = cost

    distances = floyd_warshall(adj_matrix, directed=False)
    distances[~np.isfinite(distances)] = DEFAULT_INF

    for i in range(n_v):
        for j in range(i + 1, n_v):
            sem_d = 2.0 * _safe_cosine_dist(services_embad[node_list[i]], services_embad[node_list[j]])
            distances[i, j] += sem_d
            distances[j, i] += sem_d

    app_indices = [i for i, name in enumerate(node_list) if name.startswith("Application")]
    if not app_indices:
        app_indices = list(range(n_v))

    centroid_indices = _select_centroids(node_list, services, distances, app_indices, target_k)
    k_actual = len(centroid_indices)

    # Fuzzy C-Means with m=3 -> coef = 2 / (m - 1) = 1.0 (microMiner.ipynb:730-740).
    m_fuzz = 3.0
    coef = 2.0 / (m_fuzz - 1.0)
    centroid_to_ms = {c_idx: ms_idx for ms_idx, c_idx in enumerate(centroid_indices)}

    service_assignment: Dict[int, int] = {}
    above_threshold: Dict[str, List[Dict[str, Any]]] = {
        f"microservice_{ms_idx + 1}": [] for ms_idx in range(k_actual)
    }

    for i in range(n_v):
        if i in centroid_to_ms:
            service_assignment[i] = centroid_to_ms[i]
            continue

        dists_to_c = [float(distances[i, c_idx]) for c_idx in centroid_indices]
        zero_positions = [pos for pos, d in enumerate(dists_to_c) if d <= 0.0]
        memberships: List[float]
        if zero_positions:
            memberships = [1.0 / len(zero_positions) if pos in zero_positions else 0.0 for pos in range(k_actual)]
        else:
            memberships = []
            for d_ic in dists_to_c:
                calc_weight = sum((d_ic / d_ij) ** coef for d_ij in dists_to_c)
                memberships.append(1.0 / calc_weight if calc_weight > 0.0 else 0.0)

        best_ms = int(np.argmax(memberships))
        service_assignment[i] = best_ms

        for ms_idx, val in enumerate(memberships):
            if val > soft_threshold:
                above_threshold[f"microservice_{ms_idx + 1}"].append({
                    "service": node_list[i],
                    "classes": services[node_list[i]],
                    "membership": round(val, 6),
                })

    class_labels: Dict[str, int] = {}
    for svc_idx, ms_idx in service_assignment.items():
        for cls in services[node_list[svc_idx]]:
            class_labels[cls] = ms_idx

    for cls in classes:
        class_labels.setdefault(cls, 0)

    info = {
        "k": k_actual,
        "auto_k": target_k is None,
        "application_service_count": len(app_indices),
        "service_count": n_v,
        "above_threshold_009": above_threshold,
    }
    return class_labels, info


def run_microminer(
    dataset: Dict[str, Any],
    dataset_dir: Path,
    seed: int = 42,
    target_k: Optional[int] = None,
    embedder: Optional[str] = None,
    word2vec: Optional[str] = None,
    soft_threshold: float = 0.09,
    cache_dir: Optional[Path] = None,
) -> Tuple[Dict[str, int], Dict[str, Any]]:
    """Execute the full canonical 3-phase MicroMiner pipeline on a dataset.json dict."""
    classes = extract_classes(dataset)
    if not classes:
        raise ValueError("dataset has no Java classes in dataset.json: cell is N/A")
    if target_k is not None and (target_k < 1 or target_k > len(classes)):
        raise ValueError(f"--k {target_k} must be between 1 and {len(classes)} (class count)")

    methods = dataset.get("methods", {}) or {}
    edges = dataset.get("edges", []) or []
    java_texts, resolved_count, missing_count = resolve_java_texts(dataset, dataset_dir, classes)

    # Resolve Phase 1 embedder (default: codebert; auto-fallback to tfidf only when omitted).
    embedder_requested = embedder
    embedder_fallback_reason: Optional[str] = None
    embedder_meta: Dict[str, Any] = {}

    if embedder == "tfidf":
        embedder_used = "tfidf"
        features = embed_tfidf(classes, java_texts, methods)
    elif embedder == "codebert":
        if resolved_count == 0:
            raise ValueError("CodeBERT requires .java source files on disk, but none were resolved")
        embedder_used = "codebert"
        features, embedder_meta = embed_codebert(classes, java_texts, methods, cache_dir=cache_dir)
    else:
        # Omitted (default): prefer canonical CodeBERT when torch/transformers and .java sources exist.
        if resolved_count == 0:
            embedder_used = "tfidf"
            embedder_fallback_reason = "no .java source files resolved on disk"
            features = embed_tfidf(classes, java_texts, methods)
        else:
            try:
                features, embedder_meta = embed_codebert(classes, java_texts, methods, cache_dir=cache_dir)
                embedder_used = "codebert"
            except Exception as exc:
                embedder_used = "tfidf"
                embedder_fallback_reason = f"{type(exc).__name__}: {exc}"
                features = embed_tfidf(classes, java_texts, methods)

    # Resolve Phase 3 Word2Vec mode (default: google-news; auto-fallback to corpus only when omitted).
    word2vec_requested = word2vec
    word2vec_fallback_reason: Optional[str] = None
    if word2vec == "corpus":
        w2v_used = "corpus"
    elif word2vec == "google-news":
        w2v_used = "google-news"
    else:
        try:
            import gensim.downloader  # noqa: F401
            w2v_used = "google-news"
        except Exception as exc:
            w2v_used = "corpus"
            word2vec_fallback_reason = f"{type(exc).__name__}: {exc}"

    # Phase 1: Layer classification via Linear SVM.
    layer_map, svm_meta = classify_layers_svm(classes, features, seed=seed)
    classes_by_layer: Dict[str, List[str]] = {"application": [], "entity": [], "utility": []}
    for cls, lbl in layer_map.items():
        classes_by_layer[lbl].append(cls)

    # Phase 2: Weighted Louvain + singleton refinement.
    pair_weights = aggregate_edge_weights(edges)
    typed_services = identify_typed_services(classes_by_layer, pair_weights, seed=seed)

    # Phase 3: Floyd-Warshall + Word2Vec cosine + Fuzzy C-Means.
    try:
        labels, phase3_info = phase3_map_services(
            classes=classes,
            typed_services=typed_services,
            pair_weights=pair_weights,
            java_texts=java_texts,
            methods=methods,
            w2v_mode=w2v_used,
            target_k=target_k,
            soft_threshold=soft_threshold,
        )
    except Exception as exc:
        if word2vec is None and w2v_used == "google-news":
            w2v_used = "corpus"
            word2vec_fallback_reason = f"{type(exc).__name__}: {exc}"
            labels, phase3_info = phase3_map_services(
                classes=classes,
                typed_services=typed_services,
                pair_weights=pair_weights,
                java_texts=java_texts,
                methods=methods,
                w2v_mode=w2v_used,
                target_k=target_k,
                soft_threshold=soft_threshold,
            )
        else:
            raise

    run_info: Dict[str, Any] = {
        "seed": seed,
        "k": phase3_info["k"],
        "k_requested": target_k,
        "auto_k": phase3_info["auto_k"],
        "embedder": embedder_used,
        "embedder_requested": embedder_requested or "codebert",
        "embedder_fallback_reason": embedder_fallback_reason,
        "embedder_meta": embedder_meta,
        "word2vec": w2v_used,
        "word2vec_requested": word2vec_requested or "google-news",
        "word2vec_fallback_reason": word2vec_fallback_reason,
        "soft_threshold": soft_threshold,
        "class_count": len(classes),
        "edge_count": len(edges),
        "java_files_resolved": resolved_count,
        "java_files_missing": missing_count,
        "phase1": svm_meta,
        "phase2_services": {layer: len(svcs) for layer, svcs in typed_services.items()},
        "above_threshold_009": phase3_info["above_threshold_009"],
    }
    return labels, run_info
