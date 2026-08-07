# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import json
import math
import argparse

def calculate_ned(partition, lo=5, hi=20, eps=0.5):
    """
    Non-Extreme Distribution (NED).
    Fixed bounds: 1 - (#classes in extreme-sized partitions / total classes).
    Relative bounds (CHGNN variant): proportion of classes in partitions within [floor(avg*(1-eps)), ceil(avg*(1+eps))].
    Higher is better.
    """
    clusters = {}
    for cls, cid in partition.items():
        clusters.setdefault(cid, set()).add(cls)

    total_classes = len(partition)
    if total_classes == 0 or len(clusters) == 0:
        return 0.0, 0.0, {}

    sizes = {cid: len(members) for cid, members in clusters.items()}
    
    # 1. Fixed bounds NED
    extreme_count = sum(size for size in sizes.values() if not (lo <= size <= hi))
    overall_ned = 1.0 - (extreme_count / total_classes)

    # 2. Relative bounds NED (CHGNN variant)
    avg = total_classes / len(clusters)
    rel_lo = math.floor(avg * (1.0 - eps))
    rel_hi = math.ceil(avg * (1.0 + eps))
    non_extreme_rel_count = sum(size for size in sizes.values() if rel_lo <= size <= rel_hi)
    overall_ned_relative = non_extreme_rel_count / total_classes

    microservice_scores = {}
    for cid, size in sizes.items():
        is_non_extreme = 1.0 if (lo <= size <= hi) else 0.0
        microservice_scores[cid] = is_non_extreme

    return overall_ned, overall_ned_relative, microservice_scores

def evaluate_ned(dataset_path, output_path, lo=5, hi=20, eps=0.5):
    output_json = os.path.join(output_path, "output.json")
    if not os.path.exists(output_json):
        raise FileNotFoundError(f"output.json not found at {output_json}")

    with open(output_json, "r", encoding="utf-8") as f:
        result_data = json.load(f)
        microservices = result_data.get("microservices", {})

    partition = {}
    for cid, members in microservices.items():
        for m in members:
            partition[m] = cid

    score, score_rel, ms_scores = calculate_ned(partition, lo=lo, hi=hi, eps=eps)

    print(f"Final NED Score (Fixed [{lo},{hi}]): {score:.4f}")
    print(f"Final NED Relative Score (eps={eps}): {score_rel:.4f}")

    ned_score_json = os.path.join(output_path, "ned_score.json")
    with open(ned_score_json, "w", encoding="utf-8") as f:
        json.dump({
            "metric": "NED",
            "score": score,
            "score_relative": score_rel,
            "bounds": {"lo": lo, "hi": hi, "eps": eps},
            "microservice_scores": ms_scores
        }, f, indent=4)
    print(f"Saved metric results to {ned_score_json}")
    return score

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Metric: Evaluator for Non-Extreme Distribution (NED)")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to dataset directory")
    parser.add_argument("--output-path", type=str, required=True, help="Path to tool output directory")
    parser.add_argument("--ned-lo", type=int, default=5, help="Lower bound for non-extreme partition size")
    parser.add_argument("--ned-hi", type=int, default=20, help="Upper bound for non-extreme partition size")
    parser.add_argument("--eps", type=float, default=0.5, help="Relative bound epsilon factor")
    args = parser.parse_args()

    evaluate_ned(args.dataset_path, args.output_path, lo=args.ned_lo, hi=args.ned_hi, eps=args.eps)
