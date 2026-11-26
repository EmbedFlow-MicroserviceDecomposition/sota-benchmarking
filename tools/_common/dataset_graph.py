"""Pure-Python graph views of dataset.json shared by the class-graph tools."""

from collections import defaultdict


def build_adjacency(dataset):
    """{class FQN: [dependency FQNs]} from dataset.json: every class, any edge type, deduplicated, no self edges."""
    classes = set(dataset.get("classes", ())) | {m.rsplit(".", 1)[0] for m in dataset.get("methods", {})}
    for e in dataset.get("edges", []):
        classes.update((e["src"], e["dst"]))
    adj = {c: [] for c in sorted(classes)}
    seen = defaultdict(set)
    for e in dataset.get("edges", []):
        src, dst = e["src"], e["dst"]
        if src != dst and dst not in seen[src]:
            seen[src].add(dst)
            adj[src].append(dst)
    return adj
