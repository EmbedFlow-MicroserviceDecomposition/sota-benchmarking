# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import json
import math
import argparse

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
                if "." in clean_c:
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

    class_usecases = load_class_usecases(dataset_path)
    score, ms_scores = calculate_bcp(partition, class_usecases)

    print(f"Final BCP Score: {score:.4f}")

    bcp_score_json = os.path.join(output_path, "bcp_score.json")
    with open(bcp_score_json, "w", encoding="utf-8") as f:
        json.dump({
            "metric": "BCP",
            "score": score,
            "microservice_scores": ms_scores
        }, f, indent=4)
    print(f"Saved metric results to {bcp_score_json}")
    return score

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Metric: Evaluator for Business Context Purity (BCP)")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to dataset directory")
    parser.add_argument("--output-path", type=str, required=True, help="Path to tool output directory")
    args = parser.parse_args()

    evaluate_bcp(args.dataset_path, args.output_path)
