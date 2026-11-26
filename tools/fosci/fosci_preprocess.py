"""FoSCI inputs from a raw execution trace.

write_inputs(): reduce the raw trace set Otr to the representative set Rtr (Algorithm 1 of Jin et al., TSE 2019,
"Service Candidate Identification from Monolithic Systems Based on Execution Traces"), and derive the structural call
dependency (calldep.csv: directed class->class call counts, paper section 3.2) and the concern dependency (concerndep.csv:
Jaccard of domain terms in the two classes' simple names; the paper's CMQ definition, thresholded at >= 0.2 by fosci-wrap's own
msmetric.py). fosci-wrap's release ships the optimiser but not the scripts that build these files, so they are reconstructed here.

generate_atoms(): run fosci-wrap's own unmodified atom scripts (genTestCaseFv.py -> groupclassbytrace.py ->
function_logic_identify.py, diff=3, the paper's recommended default) to obtain the Functional Atoms.
"""

import csv
import gzip
import os
import re
import subprocess
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
WRAP_DIR = os.path.join(HERE, "fosci-wrap")
sys.path.insert(0, os.path.join(HERE, "..", "..", "metrics"))
from chd.metric import _NON_DOMAIN  # noqa: E402  (the same JDK/primitive noise words as CHD)

_COLUMNS = ["traceID", "order", "structtype", "method1", "method2",
            "m1_para", "m2_para", "class1", "class2", "m1_return", "m2_return"]


def load_raw_trace(path):
    """Group rows by traceID, preserving first-seen trace order and each
    trace's internal row order. Normalizes the class1/class2 column name -
    springblog.txt uses className1/className2 while the other trace files
    use class1/class2."""
    traces = {}
    order = []
    opener = (lambda p: gzip.open(p, "rt", newline="")) if path.endswith(".gz") else (lambda p: open(p, newline=""))
    with opener(path) as f:
        reader = csv.DictReader(f)
        if "className1" in (reader.fieldnames or []):
            rename = {"className1": "class1", "className2": "class2"}
        else:
            rename = {}
        for raw_row in reader:
            row = {rename.get(k, k): v for k, v in raw_row.items()}
            tid = int(row["traceID"])
            if tid not in traces:
                traces[tid] = []
                order.append(tid)
            traces[tid].append(row)
    return [traces[tid] for tid in order]


def trace_call_set(rows):
    """set(tr): the set of method calls (m1->m2 edges) involved in a trace."""
    return frozenset((r["method1"], r["method2"]) for r in rows)


def reduce_traces(traces):
    """Algorithm 1 (Jin et al. TSE 2019): build the Representative Execution
    Trace Set Rtr from the original Otr, single left-to-right pass."""
    if not traces:
        return []
    rtr = [traces[0]]
    rtr_sets = [trace_call_set(traces[0])]
    for tri in traces[1:]:
        si = trace_call_set(tri)
        replaced = False
        kept = False
        for idx, sj in enumerate(rtr_sets):
            if sj < si:  # trj strict subset of tri -> tri replaces trj
                rtr[idx] = tri
                rtr_sets[idx] = si
                replaced = True
                break
            if si <= sj:  # tri subset of (or equal to) trj -> drop tri
                kept = True
                break
        if not replaced and not kept:
            rtr.append(tri)
            rtr_sets.append(si)
    return rtr


def write_reduced_trace(rtr, out_path):
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(_COLUMNS)
        for new_id, rows in enumerate(rtr):
            for r in rows:
                row = dict(r)
                row["traceID"] = new_id
                w.writerow([row[c] for c in _COLUMNS])


def build_calldep(rtr):
    """directed class1->class2 call-frequency counts over Rtr. getCallDep()
    in msloaddata.py sums both directions at load time, so directed counts
    here are sufficient."""
    counts = defaultdict(int)
    for rows in rtr:
        for r in rows:
            c1, c2 = r["class1"], r["class2"]
            if c1 and c2:
                counts[(c1, c2)] += 1
    return counts


def class_terms(class_fqn):
    """Domain terms of a class identifier: camelCase tokens of the simple
    name, same tokenizer as metrics.chd()'s _terms(), minus JDK/primitive
    noise words."""
    simple = class_fqn.split(".")[-1]
    words = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", simple)
    return {w.lower() for w in words} - _NON_DOMAIN


def jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def build_concerndep(classes):
    classes = sorted(classes)
    terms = {c: class_terms(c) for c in classes}
    rows = []
    for i in range(len(classes)):
        for j in range(i + 1, len(classes)):
            c1, c2 = classes[i], classes[j]
            score = jaccard(terms[c1], terms[c2])
            if score > 0:
                rows.append((c1, c2, score))
    return rows


def write_inputs(trace_path, out_dir):
    """Write workflow_reduced.csv, calldep.csv, concerndep.csv into out_dir; returns trace/class counts."""
    os.makedirs(out_dir, exist_ok=True)
    traces = load_raw_trace(trace_path)
    rtr = reduce_traces(traces)
    write_reduced_trace(rtr, os.path.join(out_dir, "workflow_reduced.csv"))

    with open(os.path.join(out_dir, "calldep.csv"), "w", newline="") as f:
        w = csv.writer(f)
        for (c1, c2), n in build_calldep(rtr).items():
            w.writerow([c1, c2, n])

    classes = {c for rows in rtr for r in rows for c in (r["class1"], r["class2"]) if c}
    with open(os.path.join(out_dir, "concerndep.csv"), "w", newline="") as f:
        w = csv.writer(f)
        for c1, c2, score in build_concerndep(classes):
            w.writerow([c1, c2, score])
    return {"traces": len(traces), "reduced": len(rtr), "classes": len(classes)}


def generate_atoms(workflow_csv, work_dir, diff=3):
    """Functional atoms of a (reduced) workflow file via fosci-wrap's scripts. Returns (atoms.csv path, #atoms)."""
    os.makedirs(work_dir, exist_ok=True)
    with open(workflow_csv, newline="") as f:
        trace_count = len({r["traceID"] for r in csv.DictReader(f)})
    files = {n: os.path.join(work_dir, n) for n in ("classFile.csv", "featureVector.csv", "classgroup.csv", "atoms.csv")}

    def run(script, *args):
        subprocess.run([sys.executable, os.path.join(WRAP_DIR, script)] + [str(a) for a in args],
                       cwd=work_dir, check=True, capture_output=True, text=True)

    run("genTestCaseFv.py", workflow_csv, trace_count, "null", "null", files["classFile.csv"], files["featureVector.csv"])
    run("groupclassbytrace.py", files["featureVector.csv"], files["classFile.csv"], files["classgroup.csv"])
    run("function_logic_identify.py", files["classgroup.csv"], diff, files["atoms.csv"])
    with open(files["atoms.csv"], newline="") as f:
        n_atoms = len({r["groupId"] for r in csv.DictReader(f)})
    return files["atoms.csv"], n_atoms
