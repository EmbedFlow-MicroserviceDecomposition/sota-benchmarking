# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#     "numpy==2.4.4",
#     "scikit-learn==1.9.0",
#     "tensorflow==2.21.0",
# ]
# ///
"""Tool: Code2Vec (Al-Debagy & Martinek, 2021) using tech-srl/code2vec AST embeddings."""

import argparse
import json
import os
import sys
import warnings

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import code2vec_adapter  # noqa: E402

TOOL = "Code2Vec"
SUBMODULE_DIR = os.path.join(HERE, "code2vec")
EXTRACTOR_JAR = os.path.join(
    SUBMODULE_DIR, "JavaExtractor", "JPredict", "target", "JavaExtractor-0.0.1-SNAPSHOT.jar"
)


def write_error(output_path, message):
    os.makedirs(output_path, exist_ok=True)
    with open(os.path.join(output_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"error": message, "tool": TOOL}, f, indent=4)
    print(f"Error written to {output_path}/output.json: {message}", file=sys.stderr)
    return 1


def membership_to_microservices(classes, labels):
    """Map integer cluster labels per class row -> {"microservice_N": sorted classes}."""
    if len(classes) != len(labels):
        raise ValueError("classes and labels must have the same length")
    groups = {}
    for cls, label in zip(classes, labels):
        groups.setdefault(int(label), []).append(cls)
    return {f"microservice_{i}": sorted(groups[lbl]) for i, lbl in enumerate(sorted(groups), 1)}


def _silhouette_fallback(vectors, seed, reason):
    """Select k in [2, min(20, N-1)] maximizing silhouette score via KMeans."""
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    n = vectors.shape[0]
    if n < 2:
        return [0] * n, {"clustering": "single_class", "k": 1, "converged": False, "fallback_reason": reason}
    n_unique = len(np.unique(vectors, axis=0))
    if n_unique < 2:
        return [0] * n, {"clustering": "silhouette_fallback", "k": 1, "converged": False, "fallback_reason": "identical_vectors"}
    if n == 2:
        labels = KMeans(n_clusters=2, random_state=seed, n_init=10).fit_predict(vectors).tolist()
        return labels, {"clustering": "silhouette_fallback", "k": len(set(labels)), "converged": False, "fallback_reason": reason}

    max_k = min(20, n - 1, n_unique)
    best_labels = None
    best_score = -2.0
    for cand_k in range(2, max_k + 1):
        cand_labels = KMeans(n_clusters=cand_k, random_state=seed, n_init=10).fit_predict(vectors)
        n_clusters = len(set(cand_labels.tolist()))
        if not (2 <= n_clusters <= n - 1):
            continue
        score = float(silhouette_score(vectors, cand_labels))
        if score > best_score:
            best_score = score
            best_labels = cand_labels.tolist()

    if best_labels is None:
        return [0] * n, {"clustering": "silhouette_fallback", "k": 1, "converged": False, "fallback_reason": reason}
    return best_labels, {
        "clustering": "silhouette_fallback",
        "k": len(set(best_labels)),
        "silhouette": best_score,
        "converged": False,
        "fallback_reason": reason,
    }


def cluster_vectors(vectors, seed=42, damping=0.5, k=None):
    """Cluster class vectors with AffinityPropagation (auto K) or fixed --k KMeans."""
    import numpy as np
    from sklearn.cluster import AffinityPropagation, KMeans
    from sklearn.exceptions import ConvergenceWarning

    vectors = np.asarray(vectors, dtype=np.float32)
    if vectors.ndim != 2 or vectors.shape[0] == 0 or not np.isfinite(vectors).all():
        raise ValueError("Class embeddings must be a non-empty finite 2D array")

    n = vectors.shape[0]
    if n == 1:
        return [0], {"clustering": "single_class", "k": 1, "converged": True}

    if k is not None:
        if k < 1 or k > n:
            raise ValueError(f"--k {k} must be between 1 and {n}")
        if k == 1:
            return [0] * n, {"clustering": "kmeans", "k": 1, "converged": True}
        if k == n:
            return list(range(n)), {"clustering": "kmeans", "k": n, "converged": True}
        labels = KMeans(n_clusters=k, random_state=seed, n_init=10).fit_predict(vectors).tolist()
        return labels, {"clustering": "kmeans", "k": len(set(labels)), "converged": True}

    estimator = AffinityPropagation(damping=damping, random_state=seed)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            labels = estimator.fit_predict(vectors)
    except ConvergenceWarning:
        return _silhouette_fallback(vectors, seed, "affinity_propagation_did_not_converge")

    if estimator.n_iter_ >= estimator.max_iter or np.any(labels < 0):
        return _silhouette_fallback(vectors, seed, "affinity_propagation_invalid_labels")

    labels_list = [int(lbl) for lbl in labels.tolist()]
    n_clusters = len(set(labels_list))
    if n_clusters <= 1:
        return _silhouette_fallback(vectors, seed, "affinity_propagation_collapsed_to_single_cluster")

    return labels_list, {
        "clustering": "affinity_propagation",
        "damping": damping,
        "iterations": int(estimator.n_iter_),
        "k": n_clusters,
        "converged": True,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tool: Code2Vec (Al-Debagy & Martinek, 2021)")
    parser.add_argument("--dataset-path", required=True, help="Dataset directory (contains dataset.json)")
    parser.add_argument("--output-path", required=True, help="Directory for output.json and raw files")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for clustering")
    parser.add_argument("--k", type=int, default=None, help="Optional fixed cluster count override")
    parser.add_argument("--damping", type=float, default=0.5, help="AffinityPropagation damping in [0.5, 1.0)")
    parser.add_argument("--model-path", type=str, default=None, help="Optional local Code2Vec checkpoint/dir path")
    args = parser.parse_args(argv)

    ds_path = os.path.abspath(args.dataset_path)
    out_path = os.path.abspath(args.output_path)
    name = os.path.basename(ds_path.rstrip("/"))

    dataset_json = os.path.join(ds_path, "dataset.json")
    if not os.path.exists(dataset_json):
        return write_error(out_path, f"dataset.json not found in {ds_path}")
    with open(dataset_json, encoding="utf-8") as f:
        dataset = json.load(f)

    classes = sorted(set(dataset.get("classes", ())) | {m.rsplit(".", 1)[0] for m in dataset.get("methods", {})})
    if not classes:
        return write_error(out_path, f"dataset '{name}' has no Java classes in dataset.json: cell is N/A")

    if not os.path.isfile(EXTRACTOR_JAR):
        return write_error(
            out_path,
            f"code2vec submodule is empty (missing {EXTRACTOR_JAR}): run `git submodule update --init`",
        )

    if not (0.5 <= args.damping < 1.0):
        return write_error(out_path, f"--damping {args.damping} must be in [0.5, 1.0)")

    if args.k is not None and (args.k < 1 or args.k > len(classes)):
        return write_error(out_path, f"--k {args.k} exceeds or invalid for the {len(classes)} classes of '{name}'")

    try:
        import numpy as np

        ckpt_prefix, dict_path = code2vec_adapter.resolve_model_files(model_path=args.model_path)
        model = code2vec_adapter.load_code2vec_model(ckpt_prefix, dict_path)
        vectors, extract_stats = code2vec_adapter.build_class_embeddings(
            dataset, ds_path, classes, EXTRACTOR_JAR, model
        )
        labels, cluster_info = cluster_vectors(
            vectors, seed=args.seed, damping=args.damping, k=args.k
        )
    except Exception as exc:
        return write_error(out_path, f"Code2Vec run failed: {exc}")

    microservices = membership_to_microservices(classes, labels)
    os.makedirs(out_path, exist_ok=True)
    np.save(os.path.join(out_path, "class_vectors.npy"), vectors)
    with open(os.path.join(out_path, "classes.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(classes) + "\n")
    with open(os.path.join(out_path, "partition.json"), "w", encoding="utf-8") as f:
        json.dump(dict(zip(classes, labels)), f, indent=4)
    with open(os.path.join(out_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"tool": TOOL, "microservices": microservices}, f, indent=4)
    run_info = {
        "dataset": dataset.get("dataset", name),
        "class_count": len(classes),
        "embedding_dimensions": int(vectors.shape[1]),
        "seed": args.seed,
        "requested_k": args.k,
        "actual_k": len(microservices),
        "checkpoint": ckpt_prefix,
        "dictionary": dict_path,
        **extract_stats,
        **cluster_info,
    }
    with open(os.path.join(out_path, "run_info.json"), "w", encoding="utf-8") as f:
        json.dump(run_info, f, indent=4)
    print(f"Code2Vec: {len(microservices)} microservices (k={len(microservices)}) -> {out_path}/output.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
