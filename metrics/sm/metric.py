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

def calculate_sm(partition_func, clusters, edges, undirected=False):
    K = len(clusters)
    if K == 0:
        return 0.0, {}

    if undirected:
        pairs = {frozenset((e.src, e.dst)) for e in edges if e.src != e.dst}
        edges = [Edge(list(p)[0], list(p)[1] if len(p) > 1 else list(p)[0], "UND", 1.0) for p in pairs]

    mu = {cid: 0 for cid in clusters}
    sigma = {}
    for e in edges:
        ci, cj = partition_func(e.src), partition_func(e.dst)
        if ci is None or cj is None:
            continue
        if ci == cj:
            mu[ci] += 2 if undirected else 1
        else:
            key = frozenset((ci, cj))
            sigma[key] = sigma.get(key, 0) + 1

    microservice_scores = {}
    for cid, members in clusters.items():
        n_k = len(members)
        if n_k == 0:
            microservice_scores[cid] = 0.0
            continue
        
        intra_k = mu[cid] / (n_k ** 2)
        if K > 1:
            inter_k = sum(
                sigma.get(frozenset((cid, j)), 0) / (2 * n_k * len(clusters[j]))
                for j in clusters if j != cid and len(clusters[j]) > 0
            ) / (K - 1)
        else:
            inter_k = 0.0
            
        microservice_scores[cid] = intra_k - inter_k

    overall_sm = sum(microservice_scores.values()) / K
    return overall_sm, microservice_scores

def evaluate_sm(dataset_path, output_path):
    dataset = load_dataset(dataset_path)
    partition = load_partition(output_path, dataset)
    edges = load_edges(dataset)
    score, ms_scores = calculate_sm(partition.get_cluster, partition.clusters, edges)
    # CHGNN's released metric.py variant: edges collapse to unordered pairs, intra pairs count twice
    score_undirected, _ = calculate_sm(partition.get_cluster, partition.clusters, edges, undirected=True)

    print(f"Final SM Score: {score:.4f}")
    print(f"Final SM Undirected Score: {score_undirected:.4f}")

    score_json = os.path.join(output_path, "sm_score.json")
    with open(score_json, "w", encoding="utf-8") as f:
        json.dump({
            "metric": "SM",
            "score": score,
            "score_undirected": score_undirected,
            "microservice_scores": ms_scores,
            "coverage": partition.coverage()
        }, f, indent=4)
    print(f"Saved metric results to {score_json}")
    return score


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Metric: Evaluator for Structural Modularity (SM)")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to dataset directory")
    parser.add_argument("--output-path", type=str, required=True, help="Path to tool output directory")
    args = parser.parse_args()

    evaluate_sm(args.dataset_path, args.output_path)
