"""Shared dataset/partition loading for every metric.

A tool's output.json may list method ids (method-level) or class FQNs (class-level):
method ids roll up to their class by majority vote, classes explode to all their methods.
"""

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass


class PartitionError(Exception):
    """output.json is an error record or cannot be read as a partition."""


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    type: str
    weight: float = 1.0


def class_of(method_id):
    """Class FQN of a method id ('pkg.Outer.Inner.method' -> 'pkg.Outer.Inner')."""
    return method_id.rsplit(".", 1)[0] if "." in method_id else method_id


def load_dataset(dataset_path):
    path = os.path.join(dataset_path, "dataset.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"dataset.json not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_edges(dataset):
    return [Edge(e["src"], e["dst"], e.get("type", "CALL"), float(e.get("weight", 1.0)))
            for e in dataset.get("edges", [])]


class Partition:
    def __init__(self, microservices, dataset):
        methods = dataset.get("methods", {})
        method_count = Counter(class_of(m) for m in methods)
        classes = set(method_count)
        for e in dataset.get("edges", []):
            classes.update((e["src"], e["dst"]))
        simple = defaultdict(set)
        for c in classes:
            simple[c.rsplit(".", 1)[-1]].add(c)

        votes = defaultdict(Counter)       # class -> {cluster: votes}
        method_cids = defaultdict(set)     # explicitly assigned method -> clusters
        class_level = set()                # classes listed directly
        kinds = set()
        self.unmatched = []

        for cid, members in microservices.items():
            for raw in members:
                m = raw.split(" [")[0].strip()
                if not m or "-res" in raw:
                    continue
                if m in methods:
                    cls, kind = class_of(m), "method"
                    method_cids[m].add(cid)
                elif m in classes:
                    cls, kind = m, "class"
                    class_level.add(m)
                elif len(simple.get(m, ())) == 1:
                    cls, kind = next(iter(simple[m])), "class"
                    class_level.add(cls)
                elif "." in m and class_of(m) in classes:
                    cls, kind = class_of(m), "method"
                else:
                    self.unmatched.append(raw)
                    continue
                kinds.add(kind)
                votes[cls][cid] += max(1, method_count[cls]) if kind == "class" else 1

        self.granularity = "mixed" if len(kinds) > 1 else (kinds.pop() if kinds else "class")
        self.by_class = {}
        self.conflicts = {}
        for cls, counter in votes.items():
            self.by_class[cls] = min(counter, key=lambda c: (-counter[c], c))
            if len(counter) > 1:
                self.conflicts[cls] = sorted(counter)

        self.by_method = {}
        for mid in methods:
            if mid in method_cids:
                self.by_method[mid] = min(method_cids[mid])
                if len(method_cids[mid]) > 1:
                    self.conflicts[mid] = sorted(method_cids[mid])
            elif class_of(mid) in class_level:
                self.by_method[mid] = self.by_class[class_of(mid)]

        # only microservices that hold at least one matched class count as clusters (K)
        self.clusters = {}
        for cls, cid in self.by_class.items():
            self.clusters.setdefault(cid, set()).add(cls)
        self.dataset_classes = classes
        self.unassigned_classes = classes - set(self.by_class)

    def get_cluster(self, node_id):
        """Cluster of a method id or class FQN, None if the node is not assigned."""
        if not node_id:
            return None
        node = node_id.split(" [")[0].strip()
        if node in self.by_method:
            return self.by_method[node]
        if node in self.by_class:
            return self.by_class[node]
        return self.by_class.get(class_of(node))

    def coverage(self):
        return {"classes": len(self.dataset_classes), "assigned": len(self.by_class),
                "unassigned": len(self.unassigned_classes),
                "unmatched_ids": len(self.unmatched), "conflicts": len(self.conflicts)}


def load_partition(output_dir, dataset):
    path = os.path.join(output_dir, "output.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"output.json not found at {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if "error" in data:
        raise PartitionError(f"{data.get('tool', 'tool')} failed: {data['error']}")
    return Partition(data.get("microservices", {}), dataset)
