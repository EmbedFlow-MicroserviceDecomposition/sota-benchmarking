# /// script
# requires-python = ">=3.11,<3.13"
# dependencies = [
#     "numpy>=2.0",
#     "scipy>=1.13",
#     "scikit-learn>=1.5",
#     "networkx>=3.0",
#     "torch>=2.1",
#     "transformers>=4.40",
#     "gensim>=4.3.3",
#     "nltk>=3.8",
# ]
# ///
"""MicroMiner CLI runner (Trabelsi et al., JSEP 2023) for the SOTA benchmark contract."""

import argparse
import json
import os
from pathlib import Path
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from microminer import run_microminer  # noqa: E402

TOOL = "MicroMiner"


def write_error(output_path, message):
    os.makedirs(output_path, exist_ok=True)
    with open(os.path.join(output_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"error": message, "tool": TOOL}, f, indent=4)
    print(f"Error written to {output_path}/output.json: {message}", file=sys.stderr)
    return 1


def labels_to_microservices(labels):
    """{class_fqn: cluster int} -> {"microservice_N": sorted classes} in cluster order."""
    clusters = {}
    for cls, cid in labels.items():
        clusters.setdefault(int(cid), []).append(cls)
    return {f"microservice_{i}": sorted(clusters[cid]) for i, cid in enumerate(sorted(clusters), 1)}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tool: MicroMiner (Trabelsi et al., JSEP 2023)")
    parser.add_argument("--dataset-path", required=True, help="Dataset directory (contains dataset.json)")
    parser.add_argument("--output-path", required=True, help="Directory for output.json and run_info.json")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (default: random, recorded in run_info.json)")
    parser.add_argument("--k", type=int, default=None, help="Optional target cluster count override (default: automatic #Application services)")
    parser.add_argument("--embedder", choices=["codebert", "tfidf"], default=None,
                        help="Phase 1 embedding backend (default: codebert, falls back to tfidf if unavailable when omitted)")
    parser.add_argument("--word2vec", choices=["google-news", "corpus"], default=None,
                        help="Phase 3 Word2Vec backend (default: google-news, falls back to corpus if unavailable when omitted)")
    parser.add_argument("--soft-threshold", type=float, default=0.09,
                        help="FCM soft membership threshold recorded in run_info.json (default: 0.09)")
    args = parser.parse_args(argv)

    ds_path = os.path.abspath(args.dataset_path)
    out_path = os.path.abspath(args.output_path)
    name = os.path.basename(ds_path.rstrip("/"))

    dataset_json = os.path.join(ds_path, "dataset.json")
    if not os.path.exists(dataset_json):
        return write_error(out_path, f"dataset.json not found in {ds_path}")

    with open(dataset_json, encoding="utf-8") as f:
        dataset = json.load(f)

    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2 ** 31)
    t0 = time.perf_counter()
    try:
        labels, info = run_microminer(
            dataset=dataset,
            dataset_dir=Path(ds_path),
            seed=seed,
            target_k=args.k,
            embedder=args.embedder,
            word2vec=args.word2vec,
            soft_threshold=args.soft_threshold,
        )
    except Exception as exc:
        msg = str(exc)
        if "cell is N/A" in msg:
            msg = f"dataset '{name}' has no Java classes in dataset.json: cell is N/A"
        return write_error(out_path, msg)

    info["dataset"] = dataset.get("dataset", name)
    info["elapsed_seconds"] = round(time.perf_counter() - t0, 3)

    if info.get("embedder_fallback_reason"):
        print(f"Warning: Phase 1 fell back to TF-IDF ({info['embedder_fallback_reason']})", file=sys.stderr)
    if info.get("word2vec_fallback_reason"):
        print(f"Warning: Phase 3 fell back to corpus Word2Vec ({info['word2vec_fallback_reason']})", file=sys.stderr)

    os.makedirs(out_path, exist_ok=True)
    microservices = labels_to_microservices(labels)
    with open(os.path.join(out_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"tool": TOOL, "microservices": microservices}, f, indent=4)
    with open(os.path.join(out_path, "run_info.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=4)

    print(
        f"MicroMiner: {len(microservices)} microservices "
        f"(k={info['k']}, seed={seed}, embedder={info['embedder']}, w2v={info['word2vec']}) -> {out_path}/output.json"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
