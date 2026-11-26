# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import json
import math
import argparse
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from partition import Edge, class_of, load_dataset, load_edges, load_partition  # noqa: E402

def calculate_bcp(partition, class_usecases, log=math.log):
    """
    Business Context Purity (BCP).
    Mean over partitions of entropy log(m_i) where m_i is the number of distinct use-case labels of member classes.
    Natural log by default. Lower is better.
    """
    clusters = {}
    for cls, cid in partition.items():
        clusters.setdefault(cid, set()).add(cls)

    K = len(clusters)
    if K == 0:
        return 0.0, {}

    microservice_scores = {}
    for cid, members in clusters.items():
        labels = set()
        for c in members:
            clean_c = c.split(" [")[0].strip()
            if clean_c in class_usecases:
                labels |= set(class_usecases[clean_c])
            elif c in class_usecases:
                labels |= set(class_usecases[c])
            else:
                short_name = clean_c.split(".")[-1]
                if short_name in class_usecases:
                    labels |= set(class_usecases[short_name])
                elif "." in clean_c:
                    parent_cls = clean_c.rsplit(".", 1)[0]
                    if parent_cls in class_usecases:
                        labels |= set(class_usecases[parent_cls])
                    else:
                        short_parent = parent_cls.split(".")[-1]
                        if short_parent in class_usecases:
                            labels |= set(class_usecases[short_parent])

        labels.discard("Unknown")
        microservice_scores[cid] = log(len(labels)) if labels else 0.0

    overall_bcp = sum(microservice_scores.values()) / K
    return overall_bcp, microservice_scores

def load_class_usecases(dataset_path):
    class_usecases = {}

    usecases_json = os.path.join(dataset_path, "usecases.json")
    if os.path.exists(usecases_json):
        try:
            with open(usecases_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                for cls, ucs in data.items():
                    class_usecases.setdefault(cls, set()).update(ucs)
        except Exception:
            pass

    dataset_json = os.path.join(dataset_path, "dataset.json")
    if os.path.exists(dataset_json):
        try:
            with open(dataset_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "usecases" in data:
                    for cls, ucs in data["usecases"].items():
                        class_usecases.setdefault(cls, set()).update(ucs)
        except Exception:
            pass

    return class_usecases

def evaluate_bcp(dataset_path, output_path):
    dataset = load_dataset(dataset_path)
    partition = load_partition(output_path, dataset)
    score, ms_scores = calculate_bcp(partition.by_class, load_class_usecases(dataset_path))

    print(f"Final BCP Score: {score:.4f}")

    score_json = os.path.join(output_path, "bcp_score.json")
    with open(score_json, "w", encoding="utf-8") as f:
        json.dump({
            "metric": "BCP",
            "score": score,
            "microservice_scores": ms_scores,
            "coverage": partition.coverage()
        }, f, indent=4)
    print(f"Saved metric results to {score_json}")
    return score


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Metric: Evaluator for Business Context Purity (BCP)")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to dataset directory")
    parser.add_argument("--output-path", type=str, required=True, help="Path to tool output directory")
    args = parser.parse_args()

    evaluate_bcp(args.dataset_path, args.output_path)
