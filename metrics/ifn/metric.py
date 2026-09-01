# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import csv
import json
import argparse
from dataclasses import dataclass

@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    type: str
    weight: float = 1.0

def resolve_partition(microservices, dataset_methods=None):
    method_partition = {}
    class_member_counts = {}

    for cid, members in microservices.items():
        for m in members:
            method_partition[m] = cid
            if dataset_methods and m in dataset_methods:
                m_info = dataset_methods[m]
                pkg = m_info.get("package", "")
                cls = m_info.get("class", "")
                class_fqn = f"{pkg}.{cls}" if pkg else cls
            else:
                class_fqn = m.rsplit(".", 1)[0] if "." in m else m

            class_member_counts.setdefault(class_fqn, {})
            class_member_counts[class_fqn][cid] = class_member_counts[class_fqn].get(cid, 0) + 1
            short_name = class_fqn.split(".")[-1]
            class_member_counts.setdefault(short_name, {})
            class_member_counts[short_name][cid] = class_member_counts[short_name].get(cid, 0) + 1

    class_partition = {}
    for class_name, counts in class_member_counts.items():
        majority_cid = max(counts.items(), key=lambda x: x[1])[0]
        class_partition[class_name] = majority_cid

    def get_cluster(node_id):
        clean_node = node_id.split(" [")[0].strip()
        if clean_node in method_partition:
            return method_partition[clean_node]
        if node_id in method_partition:
            return method_partition[node_id]
        if clean_node in class_partition:
            return class_partition[clean_node]
        if node_id in class_partition:
            return class_partition[node_id]
        if "." in clean_node:
            parent_cls = clean_node.rsplit(".", 1)[0]
            if parent_cls in class_partition:
                return class_partition[parent_cls]
            short_parent = parent_cls.split(".")[-1]
            if short_parent in class_partition:
                return class_partition[short_parent]
        return None

    return get_cluster

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

def load_edges(dataset_path):
    edges = []
    dataset_json = os.path.join(dataset_path, "dataset.json")

    if os.path.exists(dataset_json):
        with open(dataset_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "edges" in data and data["edges"]:
                for e in data["edges"]:
                    edges.append(Edge(e["src"], e["dst"], e.get("type", "CALL"), float(e.get("weight", 1.0))))
            elif "methods" in data:
                methods = data["methods"]
                for caller_id, mdata in methods.items():
                    caller_cls = mdata.get("class", caller_id.rsplit(".", 1)[0] if "." in caller_id else caller_id)
                    calls = mdata.get("calls", [])
                    for callee in calls:
                        callee_cls = callee.rsplit(".", 1)[0] if "." in callee else callee
                        edges.append(Edge(caller_cls, callee_cls, "CALL", 1.0))

    return edges

def evaluate_ifn(dataset_path, output_path):
    output_json = os.path.join(output_path, "output.json")
    if not os.path.exists(output_json):
        raise FileNotFoundError(f"output.json not found at {output_json}")

    with open(output_json, "r", encoding="utf-8") as f:
        result_data = json.load(f)
        microservices = result_data.get("microservices", {})

    dataset_methods = None
    dataset_json = os.path.join(dataset_path, "dataset.json")
    if os.path.exists(dataset_json):
        with open(dataset_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            dataset_methods = data.get("methods")

    get_cluster = resolve_partition(microservices, dataset_methods)
    clusters = set(microservices.keys())
    edges = load_edges(dataset_path)

    score, ms_scores = calculate_ifn(get_cluster, clusters, edges)

    print(f"Final IFN Score: {score:.4f}")

    ifn_score_json = os.path.join(output_path, "ifn_score.json")
    with open(ifn_score_json, "w", encoding="utf-8") as f:
        json.dump({
            "metric": "IFN",
            "score": score,
            "microservice_scores": ms_scores
        }, f, indent=4)
    print(f"Saved metric results to {ifn_score_json}")
    return score

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Metric: Evaluator for Interface Number (IFN)")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to dataset directory")
    parser.add_argument("--output-path", type=str, required=True, help="Path to tool output directory")
    args = parser.parse_args()

    evaluate_ifn(args.dataset_path, args.output_path)
