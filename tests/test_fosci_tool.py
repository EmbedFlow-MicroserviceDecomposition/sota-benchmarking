import gzip
import json
from pathlib import Path

import pytest

from conftest import load_tool

tool = load_tool("fosci")

HEADER = "traceID,order,structtype,method1,method2,m1_para,m2_para,class1,class2,m1_return,m2_return"


def make_dataset(tmp_path, name="demo", trace_rows=None, classes=("p.A",)):
    ds = tmp_path / name
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"classes": list(classes), "methods": {}, "edges": []}))
    if trace_rows is not None:
        with gzip.open(ds / "fosci_trace.csv.gz", "wt") as f:
            f.write(HEADER + "\n" + "\n".join(trace_rows) + "\n")
    return ds


def four_group_trace():
    """Eight 2-class groups, each in its own 4 traces: 8 atoms (pairwise symmetric difference 8 > 3)."""
    rows, tid = [], 0
    for g in range(8):
        a, b = f"p.G{g}A", f"p.G{g}B"
        for k in range(4):  # distinct method names keep the call sets distinct, so reduction drops nothing
            rows.append(f"{tid},0,null,{a}.m{k},{b}.n,,,{a},{b},,")
            tid += 1
    return rows


@pytest.mark.parametrize("name,atoms,expected", [
    ("jpetstore", 12, 10),       # stock K=10 when there is room
    ("bear-board", 5, 3),        # K must stay below the atom count (K=10 against 5 atoms never converges)
    ("acme-air", 7, 5),
    ("spring-petclinic", 9, 7),
    ("autocare", 12, 8),         # K=10 stalled at 12 atoms in fyp-benchmarking; 8 is the calibrated value
    ("spring-blog", 20, 8),      # paper N range 6-10, midpoint
    ("jforum", 20, 9),           # 7-11
    ("apache-roller", 40, 16),   # 14-18
])
def test_n_services_per_dataset(name, atoms, expected):
    assert tool.choose_n(name, atoms) == expected


def test_too_few_atoms_means_not_applicable():
    assert tool.choose_n("daytrader", 1) is None
    assert tool.choose_n("plants", 3) is None


def test_explicit_n_wins_but_must_stay_below_the_atom_count():
    assert tool.choose_n("jpetstore", 12, override=6) == 6
    with pytest.raises(ValueError, match="atoms"):
        tool.choose_n("jpetstore", 12, override=12)


def test_dataset_without_its_own_trace_is_an_error_output_that_is_retried_not_na(tmp_path):
    ds, out = make_dataset(tmp_path), tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "FoSCI" and "no execution trace" in data["error"] and "microservices" not in data
    assert "datasets/demo/fosci_trace.csv.gz" in data["error"]
    # the trace is an input still to be recorded, not an intrinsic N/A: `benchmark.py run` must try the cell again
    assert "N/A" not in data["error"]


def test_a_dataset_with_no_java_classes_is_a_deliberate_na(tmp_path):
    ds, out = make_dataset(tmp_path, name="genapp", classes=()), tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    error = json.loads((out / "output.json").read_text())["error"]
    assert "no Java classes" in error and "N/A" in error


def test_the_fosci_authors_published_traces_are_never_used(tmp_path, monkeypatch):
    """Only datasets/<name>/fosci_trace.csv.gz is an input, even if a trace by the authors exists for that dataset name."""
    authors = tmp_path / "FoSCI" / "traces"
    authors.mkdir(parents=True)
    (authors / "jpetstore.txt").write_text(HEADER + "\n" + "\n".join(
        f"{t},0,null,p.A.m,p.B.n,,,p.A,p.B,," for t in range(5)) + "\n")
    monkeypatch.setattr(tool, "AUTHORS_TRACES", str(authors), raising=False)    # the old code path would find this file
    ds, out = make_dataset(tmp_path, name="jpetstore"), tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    assert "no execution trace" in json.loads((out / "output.json").read_text())["error"]


def test_degenerate_trace_with_too_few_atoms_is_an_error_output(tmp_path):
    rows = [f"{t},0,null,p.A.m,p.B.n,,,p.A,p.B,," for t in range(5)]
    ds, out = make_dataset(tmp_path, trace_rows=rows), tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    assert "functional atoms" in json.loads((out / "output.json").read_text())["error"]


def test_end_to_end_on_a_tiny_trace_partitions_every_traced_class(tmp_path):
    ds, out = make_dataset(tmp_path, trace_rows=four_group_trace()), tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 0
    data = json.loads((out / "output.json").read_text())
    classes = sorted(c for members in data["microservices"].values() for c in members)
    assert classes == sorted(f"p.G{g}{x}" for g in range(8) for x in "AB")
    info = json.loads((out / "run_info.json").read_text())
    assert info["atoms"] == 8 and info["n_services"] == 6 and info["traces"] == 32
