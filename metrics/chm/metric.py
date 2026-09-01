# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import json
import argparse
from dataclasses import dataclass
from itertools import combinations

@dataclass(frozen=True)
class Operation:
    cls: str
    name: str
    params: tuple
    returns: str

def _jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)

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

def _published_ops(get_cluster, clusters, calls):
    ops = {cid: set() for cid in clusters}
    for caller, op in calls:
        ci, cj = get_cluster(caller), get_cluster(op.cls)
        if ci is None or cj is None or ci == cj:
            continue
        ops[cj].add(op)
    return ops

def _pairwise_mean(ops, similarity):
    ops = sorted(ops, key=lambda o: (o.cls, o.name, o.params, o.returns))
    if len(ops) < 2:
        return 1.0
    pairs = list(combinations(ops, 2))
    return sum(similarity(a, b) for a, b in pairs) / len(pairs)

def calculate_chm(get_cluster, clusters, calls):
    """
    Cohesion at Message Level (CHM).
    Canonical formulation (Jin et al., TSE 2021):
    f_msg = (Jaccard(returns) + Jaccard(params)) / 2 over externally-invoked operations.
    Range [0, 1], higher is better.
    """
    def f_msg(a, b):
        return (_jaccard({a.returns}, {b.returns}) + _jaccard(a.params, b.params)) / 2.0

    ops_per_ms = _published_ops(get_cluster, clusters, calls)
    active_ms = [cid for cid, ops in ops_per_ms.items() if len(ops) >= 2]
    if not active_ms:
        return 1.0, {cid: 1.0 for cid in clusters}

    microservice_scores = {}
    for cid in clusters:
        ops = ops_per_ms.get(cid, set())
        microservice_scores[cid] = _pairwise_mean(ops, f_msg)

    overall_chm = sum(microservice_scores.values()) / len(clusters)
    return overall_chm, microservice_scores

def load_calls(dataset_path):
    calls = []
    dataset_methods = {}
    dataset_json = os.path.join(dataset_path, "dataset.json")

    if os.path.exists(dataset_json):
        with open(dataset_json, "r", encoding="utf-8") as f:
            data = json.load(f)
            methods = data.get("methods", {})
            dataset_methods = methods
            for caller_id, mdata in methods.items():
                caller_cls = mdata.get("class", caller_id.rsplit(".", 1)[0] if "." in caller_id else caller_id)
                method_calls = mdata.get("calls", [])
                for callee_id in method_calls:
                    callee_data = methods.get(callee_id, {})
                    callee_cls = callee_data.get("class", callee_id.rsplit(".", 1)[0] if "." in callee_id else callee_id)
                    callee_name = callee_data.get("method_name", callee_id.split(".")[-1])
                    callee_params = tuple(callee_data.get("parameters", []))
                    callee_returns = callee_data.get("return_type", "void")
                    
                    op = Operation(cls=callee_cls, name=callee_name, params=callee_params, returns=callee_returns)
                    calls.append((caller_cls, op))

    return calls, dataset_methods

def evaluate_chm(dataset_path, output_path):
    output_json = os.path.join(output_path, "output.json")
    if not os.path.exists(output_json):
        raise FileNotFoundError(f"output.json not found at {output_json}")

    with open(output_json, "r", encoding="utf-8") as f:
        result_data = json.load(f)
        microservices = result_data.get("microservices", {})

    calls, dataset_methods = load_calls(dataset_path)
    get_cluster = resolve_partition(microservices, dataset_methods)
    clusters = set(microservices.keys())

    score, ms_scores = calculate_chm(get_cluster, clusters, calls)

    print(f"Final CHM Score: {score:.4f}")

    chm_score_json = os.path.join(output_path, "chm_score.json")
    with open(chm_score_json, "w", encoding="utf-8") as f:
        json.dump({
            "metric": "CHM",
            "score": score,
            "microservice_scores": ms_scores
        }, f, indent=4)
    print(f"Saved metric results to {chm_score_json}")
    return score

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Metric: Evaluator for Cohesion at Message Level (CHM)")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to dataset directory")
    parser.add_argument("--output-path", type=str, required=True, help="Path to tool output directory")
    args = parser.parse_args()

    evaluate_chm(args.dataset_path, args.output_path)
