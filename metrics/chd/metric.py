# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import re
import json
import argparse
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from partition import Edge, class_of, load_dataset, load_edges, load_partition  # noqa: E402
from dataclasses import dataclass
from itertools import combinations

_NON_DOMAIN = {
    "void", "int", "long", "short", "byte", "float", "double", "boolean",
    "char", "string", "list", "map", "set", "collection", "object",
    "integer", "optional", "iterable",
}

@dataclass(frozen=True)
class Operation:
    cls: str
    name: str
    params: tuple
    returns: str

def _terms(op):
    words = []
    names = [op.name] + [p.split(".")[-1] for p in op.params]
    names.append(op.returns.split(".")[-1])
    for name in names:
        words.extend(re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", name))
    return {w.lower() for w in words} - _NON_DOMAIN

def _jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)

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

def calculate_chd(get_cluster, clusters, calls):
    """
    Cohesion at Domain Level (CHD).
    Mean over partitions of the mean pairwise Jaccard similarity of domain terms in operation signatures.
    Range [0, 1], higher is better.
    """
    def f_dom(a, b):
        return _jaccard(_terms(a), _terms(b))

    ops_per_ms = _published_ops(get_cluster, clusters, calls)
    active_ms = [cid for cid, ops in ops_per_ms.items() if len(ops) >= 2]
    if not active_ms:
        return 1.0, {cid: 1.0 for cid in clusters}

    microservice_scores = {}
    for cid in clusters:
        ops = ops_per_ms.get(cid, set())
        microservice_scores[cid] = _pairwise_mean(ops, f_dom)

    overall_chd = sum(microservice_scores.values()) / len(clusters)
    return overall_chd, microservice_scores

def load_calls(dataset):
    """(caller class FQN, Operation) for every project call site in dataset.json."""
    methods = dataset.get("methods", {})
    calls = []
    for caller_id, mdata in methods.items():
        for callee_id in mdata.get("calls", []):
            callee = methods.get(callee_id, {})
            op = Operation(cls=class_of(callee_id),
                           name=callee.get("method_name", callee_id.split(".")[-1]),
                           params=tuple(callee.get("parameters", [])),
                           returns=callee.get("return_type", "void"))
            calls.append((class_of(caller_id), op))
    return calls


def evaluate_chd(dataset_path, output_path):
    dataset = load_dataset(dataset_path)
    partition = load_partition(output_path, dataset)
    score, ms_scores = calculate_chd(partition.get_cluster, partition.clusters, load_calls(dataset))

    print(f"Final CHD Score: {score:.4f}")

    score_json = os.path.join(output_path, "chd_score.json")
    with open(score_json, "w", encoding="utf-8") as f:
        json.dump({
            "metric": "CHD",
            "score": score,
            "microservice_scores": ms_scores,
            "coverage": partition.coverage()
        }, f, indent=4)
    print(f"Saved metric results to {score_json}")
    return score


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Metric: Evaluator for Cohesion at Domain Level (CHD)")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to dataset directory")
    parser.add_argument("--output-path", type=str, required=True, help="Path to tool output directory")
    args = parser.parse_args()

    evaluate_chd(args.dataset_path, args.output_path)
