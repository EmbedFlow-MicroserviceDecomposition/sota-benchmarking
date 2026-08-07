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
            # 1. Exact match
            if c in class_usecases:
                labels |= set(class_usecases[c])
            else:
                # 2. Parent class FQN and short class name
                if "." in c:
                    parent_cls = c.rsplit(".", 1)[0]
                    if parent_cls in class_usecases:
                        labels |= set(class_usecases[parent_cls])
                    else:
                        short_parent = parent_cls.split(".")[-1]
                        if short_parent in class_usecases:
                            labels |= set(class_usecases[short_parent])
                else:
                    if c in class_usecases:
                        labels |= set(class_usecases[c])

        # Exclude internal "Unknown" usecase if present
        labels.discard("Unknown")
        microservice_scores[cid] = log(len(labels)) if labels else 0.0

    overall_bcp = sum(microservice_scores.values()) / K
    return overall_bcp, microservice_scores

def load_class_usecases(dataset_path, output_path):
    class_usecases = {}

    # 1. Check final_graph.json / cardinal_graph.json in Mono2Micro output
    oriole_graph = os.path.join(output_path, "mono2micro", "mono2micro-output", "oriole", "final_graph.json")
    cardinal_graph = os.path.join(output_path, "mono2micro", "mono2micro-output", "cardinal", "final_graph.json")
    for gf in [oriole_graph, cardinal_graph]:
        if os.path.exists(gf):
            try:
                with open(gf, "r", encoding="utf-8") as f:
                    gdata = json.load(f)
                    cg = gdata.get("mono_run_time_call_graph", {})
                    nodes = cg.get("nodes", [])
                    for node in nodes:
                        name = node.get("name", "")
                        semantics = node.get("semantics", [])
                        if name and semantics:
                            clean_name = name.split(" [")[0].strip()
                            class_usecases.setdefault(clean_name, set()).update(semantics)
                            class_usecases.setdefault(name, set()).update(semantics)
                            filepath = node.get("filepath", "")
                            if "Class," in filepath:
                                path_part = filepath.split("Class,")[-1].strip()
                                cls_name = os.path.splitext(os.path.basename(path_part))[0]
                                class_usecases.setdefault(cls_name, set()).update(semantics)
            except Exception:
                pass

    # 2. Check usecases.json files
    usecase_files = [
        os.path.join(output_path, "usecases.json"),
        os.path.join(output_path, "contexts", "usecases.json"),
        os.path.join(dataset_path, "usecases.json")
    ]
    for uf in usecase_files:
        if os.path.exists(uf):
            try:
                with open(uf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, list):
                                for item in v:
                                    class_usecases.setdefault(item, set()).add(k)
                                    class_usecases.setdefault(k, set()).update(v)
            except Exception:
                pass

    # 3. Check dataset.json
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

    class_usecases = load_class_usecases(dataset_path, output_path)
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
