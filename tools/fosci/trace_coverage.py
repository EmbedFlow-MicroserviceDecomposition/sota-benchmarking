# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""How much of a dataset an execution trace exercises: classes and methods of dataset.json that appear in it.

Coverage counts what FoSCI can see: a class is covered when it is the caller or callee of a recorded call. Interfaces
(e.g. MyBatis mappers, run through generated proxies) have no bytecode of their own to instrument, so they are reported
separately and also excluded from `traceable_class_coverage`.

    uv run trace_coverage.py --dataset-path ../../datasets/jpetstore [--trace other.csv.gz] [--min 0.7]
"""

import argparse
import csv
import gzip
import json
import os
import re
import sys

TARGET = 0.70


def read_trace(path):
    """(classes, methods, number of traces) named in a raw FoSCI trace (.csv or .csv.gz)."""
    opener = gzip.open if path.endswith(".gz") else open
    classes, methods, trace_ids = set(), set(), set()
    with opener(path, "rt", newline="") as f:
        for row in csv.DictReader(f):
            trace_ids.add(row["traceID"])
            for c in (row.get("class1") or row.get("className1"), row.get("class2") or row.get("className2")):
                if c:
                    classes.add(c)
            for m in (row["method1"], row["method2"]):
                if m:
                    methods.add(m)
    return classes, methods, len(trace_ids)


def resolve(name, known):
    """Map a JVM class name onto a dataset.json class: `$` -> `.`, anonymous/local classes roll up to their owner."""
    name = name.replace("$", ".")
    while name:
        if name in known:
            return name
        name = name.rpartition(".")[0]
    return None


def interfaces(dataset, dataset_dir):
    """Classes declared as interfaces in their source file."""
    files = {}
    for m in dataset["methods"].values():
        if m.get("file_path"):
            files.setdefault(f'{m["package"]}.{m["class"]}', m["file_path"])
    source_root = os.path.join(dataset_dir, dataset.get("source_path") or "")
    found = set()
    for cls in dataset["classes"]:
        simple = cls.rpartition(".")[2]
        path = os.path.join(source_root, files[cls]) if cls in files else None
        if path is None:  # no methods recorded: look for the top-level file of its package path
            parts = cls.split(".")
            for i in range(len(parts), 0, -1):
                candidate = os.path.join(*parts[:i]) + ".java"
                hits = [p for p in _java_files(source_root) if p.endswith(os.sep + candidate)]
                if hits:
                    path = hits[0]  # already includes source_root
                    break
        if path is None:
            continue
        try:
            src = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        if re.search(rf"\binterface\s+{re.escape(simple)}\b", src):
            found.add(cls)
    return found


_JAVA_FILES = {}


def _java_files(root):
    if root not in _JAVA_FILES:
        _JAVA_FILES[root] = [os.path.join(d, f) for d, _, fs in os.walk(root) for f in fs if f.endswith(".java")]
    return _JAVA_FILES[root]


def coverage(dataset_dir, trace_path):
    dataset = json.load(open(os.path.join(dataset_dir, "dataset.json"), encoding="utf-8"))
    known = set(dataset["classes"])
    trace_classes, trace_methods, n_traces = read_trace(trace_path)

    covered, unmatched = set(), set()
    for c in trace_classes:
        hit = resolve(c, known)
        (covered.add(hit) if hit else unmatched.add(c))

    method_ids = set(dataset["methods"])
    covered_methods = set()
    for m in trace_methods:
        cls, _, meth = m.rpartition(".")
        owner = resolve(cls, known)
        if owner and f"{owner}.{meth}" in method_ids:
            covered_methods.add(f"{owner}.{meth}")

    ifaces = interfaces(dataset, dataset_dir)
    traceable = known - ifaces
    ratio = lambda a, b: round(len(a) / len(b), 4) if b else 0.0  # noqa: E731
    return {
        "dataset": os.path.basename(os.path.abspath(dataset_dir)),
        "trace": os.path.relpath(trace_path, dataset_dir),
        "traces": n_traces,
        "classes": len(known),
        "classes_covered": len(covered),
        "class_coverage": ratio(covered, known),
        "traceable_classes": len(traceable),
        "traceable_class_coverage": ratio(covered & traceable, traceable),
        "methods": len(method_ids),
        "methods_covered": len(covered_methods),
        "method_coverage": ratio(covered_methods, method_ids),
        "target": TARGET,
        "uncovered_classes": sorted(traceable - covered),
        "uncovered_interfaces": sorted(ifaces - covered),
        "unmatched_trace_classes": sorted(unmatched),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--trace", help="default: <dataset>/fosci_trace.csv.gz")
    parser.add_argument("--output", help="default: <dataset>/fosci_trace_coverage.json")
    parser.add_argument("--min", type=float, default=TARGET, help="exit 1 below this class coverage (default 0.70)")
    args = parser.parse_args()

    trace = args.trace or os.path.join(args.dataset_path, "fosci_trace.csv.gz")
    if not os.path.exists(trace):
        sys.exit(f"no trace at {trace}")
    report = coverage(args.dataset_path, trace)
    with open(args.output or os.path.join(args.dataset_path, "fosci_trace_coverage.json"), "w") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(f"{report['dataset']}: {report['traces']} traces, classes {report['classes_covered']}/{report['classes']} "
          f"({report['class_coverage']:.0%}; {report['traceable_class_coverage']:.0%} of non-interfaces), "
          f"methods {report['methods_covered']}/{report['methods']} ({report['method_coverage']:.0%})")
    if report["uncovered_classes"]:
        print("  uncovered: " + ", ".join(report["uncovered_classes"]))
    if report["uncovered_interfaces"]:
        print("  uncovered interfaces (not instrumentable): " + ", ".join(report["uncovered_interfaces"]))
    if report["class_coverage"] < args.min:
        print(f"  BELOW TARGET: class coverage {report['class_coverage']:.0%} < {args.min:.0%}")
        sys.exit(1)


if __name__ == "__main__":
    main()
