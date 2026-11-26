"""CLI driver shared by tools/ae-k and tools/vae-c: dataset.json + entrypoints.txt -> output.json."""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dataset_graph import build_adjacency  # noqa: E402


def write_error(output_path, tool, message):
    os.makedirs(output_path, exist_ok=True)
    with open(os.path.join(output_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"error": message, "tool": tool}, f, indent=4)
    print(f"Error written to {output_path}/output.json: {message}", file=sys.stderr)
    return 1


def labels_to_microservices(labels):
    """{class: cluster int} -> {"microservice_N": sorted classes}, clusters in id order."""
    clusters = {}
    for cls, cid in labels.items():
        clusters.setdefault(cid, []).append(cls)
    return {f"microservice_{i}": sorted(clusters[cid]) for i, cid in enumerate(sorted(clusters), 1)}


def main(tool, run, argv=None, paper_k=None, description=""):
    """`run(adj, entrypoints, seed, max_paths, n_epochs, k, info) -> {class: cluster}`; paper_k: {dataset: fixed k}."""
    parser = argparse.ArgumentParser(description=description or f"Tool: {tool}")
    parser.add_argument("--dataset-path", required=True, help="Dataset directory (dataset.json + entrypoints.txt)")
    parser.add_argument("--output-path", required=True, help="Directory for output.json and raw files")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (default: random, recorded in run_info.json)")
    parser.add_argument("--max-paths", type=int, default=20000, help="Cap on explored co-entrypoint paths per entrypoint")
    parser.add_argument("--n-epochs", type=int, default=8000)
    if paper_k is not None:
        parser.add_argument("--k", type=int, default=None,
                            help="Fixed cluster count (default: the thesis's k=5 on its own datasets, else SSE elbow)")
    args = parser.parse_args(argv)

    ds_path = os.path.abspath(args.dataset_path)
    out_path = os.path.abspath(args.output_path)
    name = os.path.basename(ds_path.rstrip("/"))

    dataset_json = os.path.join(ds_path, "dataset.json")
    if not os.path.exists(dataset_json):
        return write_error(out_path, tool, f"dataset.json not found in {ds_path}")
    entrypoints_file = os.path.join(ds_path, "entrypoints.txt")
    if not os.path.exists(entrypoints_file):
        return write_error(out_path, tool, f"entrypoints.txt not found in {ds_path}: {tool} needs web entrypoint "
                                           "classes; cell is N/A")
    with open(dataset_json, encoding="utf-8") as f:
        dataset = json.load(f)
    with open(entrypoints_file, encoding="utf-8") as f:
        entrypoints = [line.strip() for line in f if line.strip()]

    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2 ** 31)
    k = getattr(args, "k", None)
    if k is None and paper_k:
        k = paper_k.get(name)
    info = {}
    try:
        labels = run(build_adjacency(dataset), entrypoints, seed, args.max_paths, args.n_epochs, k, info)
    except ValueError as e:
        return write_error(out_path, tool, str(e))

    os.makedirs(out_path, exist_ok=True)
    microservices = labels_to_microservices(labels)
    with open(os.path.join(out_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"tool": tool, "microservices": microservices}, f, indent=4)
    with open(os.path.join(out_path, "run_info.json"), "w", encoding="utf-8") as f:
        json.dump({"seed": seed, "k": info.get("k"), "capped": info.get("capped")}, f, indent=4)
    print(f"{tool}: {len(microservices)} microservices (k={info.get('k')}, seed={seed}) -> {out_path}/output.json")
    return 0
