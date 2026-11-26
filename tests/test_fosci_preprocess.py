import csv
import gzip
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "fosci"))
import fosci_preprocess as fp  # noqa: E402

HEADER = "traceID,order,structtype,method1,method2,m1_para,m2_para,class1,class2,m1_return,m2_return"


def row(tid, order, c1, c2, m1="m", m2="n"):
    return f"{tid},{order},null,{c1}.{m1},{c2}.{m2},,,{c1},{c2},,"


def write_trace(path, rows, header=HEADER, gz=False):
    text = header + "\n" + "\n".join(rows) + "\n"
    if gz:
        with gzip.open(path, "wt") as f:
            f.write(text)
    else:
        Path(path).write_text(text)


def trace(*calls):
    """A trace given as (class1, class2) pairs -> list of row dicts."""
    return [{"traceID": "0", "order": str(i), "structtype": "null", "method1": f"{a}.m", "method2": f"{b}.n",
             "m1_para": "", "m2_para": "", "class1": a, "class2": b, "m1_return": "", "m2_return": ""}
            for i, (a, b) in enumerate(calls)]


def test_a_trace_whose_calls_are_a_subset_of_another_is_dropped():
    small, big = trace(("A", "B")), trace(("A", "B"), ("B", "C"))
    assert fp.reduce_traces([big, small]) == [big]


def test_a_later_superset_replaces_the_earlier_subset():
    small, big = trace(("A", "B")), trace(("A", "B"), ("B", "C"))
    assert fp.reduce_traces([small, big]) == [big]


def test_equal_and_disjoint_traces():
    t1, t2, t3 = trace(("A", "B")), trace(("A", "B")), trace(("C", "D"))
    assert fp.reduce_traces([t1, t2, t3]) == [t1, t3]


def test_calldep_counts_directed_class_calls():
    dep = fp.build_calldep([trace(("A", "B"), ("A", "B"), ("B", "A"))])
    assert dep == {("A", "B"): 2, ("B", "A"): 1}


def test_concerndep_is_the_jaccard_of_camelcase_name_terms_and_drops_zero_pairs():
    rows = fp.build_concerndep(["x.OrderService", "x.OrderRepo", "x.Account"])
    assert rows == [("x.OrderRepo", "x.OrderService", pytest.approx(1 / 3))]


def test_load_raw_trace_reads_gzip_and_normalises_classname_columns(tmp_path):
    header = HEADER.replace("class1,class2", "className1,className2")
    p = tmp_path / "t.csv.gz"
    write_trace(p, [row(0, 0, "A", "B"), row(0, 1, "B", "C"), row(1, 0, "A", "C")], header=header, gz=True)
    traces = fp.load_raw_trace(str(p))
    assert [len(t) for t in traces] == [2, 1]
    assert traces[0][0]["class1"] == "A" and traces[0][0]["class2"] == "B"


def test_write_inputs_renumbers_traces_and_reports_counts(tmp_path):
    raw = tmp_path / "raw.csv"
    write_trace(raw, [row(5, 0, "p.A", "p.B"), row(5, 1, "p.B", "p.C"), row(9, 0, "p.A", "p.B"), row(12, 0, "p.X", "p.Y")])
    out = tmp_path / "out"
    info = fp.write_inputs(str(raw), str(out))
    assert info == {"traces": 3, "reduced": 2, "classes": 5}
    ids = {r["traceID"] for r in csv.DictReader(open(out / "workflow_reduced.csv"))}
    assert ids == {"0", "1"}
    assert (out / "calldep.csv").exists() and (out / "concerndep.csv").exists()


def test_generate_atoms_groups_classes_that_share_trace_participation(tmp_path):
    rows = []
    for t in range(4):      # classes A,B appear together in traces 0-3 ...
        rows += [row(t, 0, "p.A", "p.B")]
    for t in range(4, 8):   # ... C,D together in traces 4-7: symmetric difference 8 > diff=3
        rows += [row(t, 0, "p.C", "p.D")]
    raw = tmp_path / "raw.csv"
    write_trace(raw, rows)
    atoms_csv, n_atoms = fp.generate_atoms(str(raw), str(tmp_path / "work"))
    assert n_atoms == 2
    groups = {r["classname"]: r["groupId"] for r in csv.DictReader(open(atoms_csv))}
    assert groups["p.A"] == groups["p.B"] and groups["p.C"] == groups["p.D"] and groups["p.A"] != groups["p.C"]
