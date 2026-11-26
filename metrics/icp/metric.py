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

def calculate_icp(get_cluster, clusters, edges):
    total = 0.0
    crossing = 0.0

    ms_total = {cid: 0.0 for cid in clusters}
    ms_crossing = {cid: 0.0 for cid in clusters}

    for e in edges:
        if e.type != "CALL":
            continue
        ci, cj = get_cluster(e.src), get_cluster(e.dst)
        if ci is None or cj is None:
            continue

        total += e.weight
        ms_total[ci] = ms_total.get(ci, 0.0) + e.weight

        if ci != cj:
            crossing += e.weight
            ms_crossing[ci] = ms_crossing.get(ci, 0.0) + e.weight

    microservice_scores = {}
    for cid in clusters:
        tot = ms_total.get(cid, 0.0)
        cros = ms_crossing.get(cid, 0.0)
        microservice_scores[cid] = cros / tot if tot > 0 else 0.0

    overall_icp = crossing / total if total > 0 else 0.0
    return overall_icp, microservice_scores

def evaluate_icp(dataset_path, output_path):
    dataset = load_dataset(dataset_path)
    partition = load_partition(output_path, dataset)
    score, ms_scores = calculate_icp(partition.get_cluster, partition.clusters, load_edges(dataset))

    print(f"Final ICP Score: {score:.4f}")

    score_json = os.path.join(output_path, "icp_score.json")
    with open(score_json, "w", encoding="utf-8") as f:
        json.dump({
            "metric": "ICP",
            "score": score,
            "microservice_scores": ms_scores,
            "coverage": partition.coverage()
        }, f, indent=4)
    print(f"Saved metric results to {score_json}")
    return score


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Metric: Evaluator for Inter-Call Percentage (ICP)")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to dataset directory")
    parser.add_argument("--output-path", type=str, required=True, help="Path to tool output directory")
    args = parser.parse_args()

    evaluate_icp(args.dataset_path, args.output_path)
