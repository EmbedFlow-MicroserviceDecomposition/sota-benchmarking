# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import csv
import json
import argparse
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from partition import Edge, class_of, load_dataset, load_edges, load_partition  # noqa: E402

def calculate_ifn(get_cluster, clusters, edges):
    K = len(clusters)
    if K == 0:
        return 0.0, {}

    interfaces_per_ms = {cid: set() for cid in clusters}

    for e in edges:
        if e.type != "CALL":
            continue
        ci, cj = get_cluster(e.src), get_cluster(e.dst)
        if ci is None or cj is None or ci == cj:
            continue
        interfaces_per_ms[cj].add(e.dst)

    microservice_scores = {cid: float(len(ifaces)) for cid, ifaces in interfaces_per_ms.items()}
    overall_ifn = sum(microservice_scores.values()) / K
    return overall_ifn, microservice_scores

def calculate_ifn_cross_edge(get_cluster, clusters, edges):
    """CHGNN released-repo IFN: distinct undirected cross-partition node pairs (any edge type) per partition."""
    pairs = {frozenset((e.src, e.dst)) for e in edges if e.src != e.dst}
    cross = 0
    for pair in pairs:
        a, b = tuple(pair)
        ci, cj = get_cluster(a), get_cluster(b)
        if ci is not None and cj is not None and ci != cj:
            cross += 1
    return cross / len(clusters) if clusters else 0.0

def evaluate_ifn(dataset_path, output_path):
    dataset = load_dataset(dataset_path)
    partition = load_partition(output_path, dataset)
    edges = load_edges(dataset)
    score, ms_scores = calculate_ifn(partition.get_cluster, partition.clusters, edges)
    score_cross_edge = calculate_ifn_cross_edge(partition.get_cluster, partition.clusters, edges)

    print(f"Final IFN Score: {score:.4f}")
    print(f"Final IFN Cross-Edge Score: {score_cross_edge:.4f}")

    score_json = os.path.join(output_path, "ifn_score.json")
    with open(score_json, "w", encoding="utf-8") as f:
        json.dump({
            "metric": "IFN",
            "score": score,
            "score_cross_edge": score_cross_edge,
            "microservice_scores": ms_scores,
            "coverage": partition.coverage()
        }, f, indent=4)
    print(f"Saved metric results to {score_json}")
    return score


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Metric: Evaluator for Interface Number (IFN)")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to dataset directory")
    parser.add_argument("--output-path", type=str, required=True, help="Path to tool output directory")
    args = parser.parse_args()

    evaluate_ifn(args.dataset_path, args.output_path)
