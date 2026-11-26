"""dataset.json -> CoGCN input folder (struct.csv, content.csv; the layout of cogcn/data/apps/<app>/).

struct.csv   n x n symmetric 0/1 adjacency over classes (any edge type, no self loops), no header.
content.csv  n x d term-frequency rows, no header: the terms of a class's own name, its method names, and its method
             parameter/return type names (camelCase tokens, JDK/primitive noise words dropped, as in metrics/chd), each
             row normalised to sum 1.
classes.txt  row order (sorted class FQNs); vocabulary.txt column order.
"""

import csv
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "metrics"))
from chd.metric import _NON_DOMAIN  # noqa: E402

_WORD = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


def terms(identifier):
    """Lower-case camelCase tokens of an identifier, noise words removed."""
    simple = identifier.rsplit(".", 1)[-1]
    return [w.lower() for w in _WORD.findall(simple) if w.lower() not in _NON_DOMAIN]


def build_cogcn_inputs(dataset, out_dir):
    classes = sorted(set(dataset.get("classes", ())) | {m.rsplit(".", 1)[0] for m in dataset.get("methods", {})}
                     | {c for e in dataset.get("edges", []) for c in (e["src"], e["dst"])})
    index = {c: i for i, c in enumerate(classes)}
    n = len(classes)

    adj = [[0] * n for _ in range(n)]
    for e in dataset.get("edges", []):
        i, j = index[e["src"]], index[e["dst"]]
        if i != j:
            adj[i][j] = adj[j][i] = 1

    counts = {c: Counter(terms(c)) for c in classes}
    for mid, m in dataset.get("methods", {}).items():
        cls = counts[mid.rsplit(".", 1)[0]]
        for ident in [m["method_name"], m.get("return_type", "")] + list(m.get("parameters", [])):
            cls.update(terms(ident))
    vocab = sorted({t for c in counts.values() for t in c})

    rows = []
    for c in classes:
        total = sum(counts[c].values())
        rows.append([counts[c][t] / total if total else 0.0 for t in vocab] or [0.0])

    os.makedirs(out_dir, exist_ok=True)
    for name, matrix in (("struct.csv", adj), ("content.csv", rows)):
        with open(os.path.join(out_dir, name), "w", newline="") as f:
            csv.writer(f).writerows(matrix)
    with open(os.path.join(out_dir, "classes.txt"), "w") as f:
        f.write("\n".join(classes) + "\n")
    with open(os.path.join(out_dir, "vocabulary.txt"), "w") as f:
        f.write("\n".join(vocab) + ("\n" if vocab else ""))
    return {"classes": n, "terms": len(vocab), "edges": sum(map(sum, adj)) // 2}
