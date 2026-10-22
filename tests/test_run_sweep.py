import json
import statistics
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_sweep  # noqa: E402

CLASSES = [f"p.C{i}" for i in range(6)]
DATASET = {
    "classes": CLASSES, "methods": {},
    "edges": [{"src": a, "dst": b, "type": "CALL", "weight": 1.0}
              for a, b in [("p.C0", "p.C1"), ("p.C1", "p.C2"), ("p.C2", "p.C3"), ("p.C3", "p.C4"), ("p.C4", "p.C5"),
                           ("p.C0", "p.C3")]],
}

# a fake tool whose partition depends on how many times it has been run, so runs differ
FAKE_TOOL = textwrap.dedent('''
    import json, os, sys
    out = sys.argv[sys.argv.index("--output-path") + 1]
    counter = os.path.join(os.path.dirname(os.path.abspath(__file__)), "count.txt")
    n = int(open(counter).read()) if os.path.exists(counter) else 0
    open(counter, "w").write(str(n + 1))
    os.makedirs(out, exist_ok=True)
    classes = [f"p.C{i}" for i in range(6)]
    mode = os.environ.get("FAKE_MODE", "ok")
    if mode == "error" or (mode == "flaky" and n == 1):
        json.dump({"error": "boom", "tool": "Fake"}, open(os.path.join(out, "output.json"), "w"))
        sys.exit(1)
    split = 3 if n % 2 == 0 else 2
    ms = {"microservice_1": classes[:split], "microservice_2": classes[split:]}
    if mode == "nested":
        for k in (2, 3):
            d = os.path.join(out, "runs", f"k{k}")
            os.makedirs(d, exist_ok=True)
            json.dump({"tool": "Fake", "microservices": {"microservice_1": classes[:k], "microservice_2": classes[k:]}},
                      open(os.path.join(d, "output.json"), "w"))
        sys.exit(0)
    json.dump({"tool": "Fake", "microservices": ms}, open(os.path.join(out, "output.json"), "w"))
''')


@pytest.fixture()
def cell(tmp_path):
    tool_dir = tmp_path / "tools" / "fake"
    tool_dir.mkdir(parents=True)
    (tool_dir / "tool.py").write_text(FAKE_TOOL)
    ds = tmp_path / "datasets" / "demo"
    ds.mkdir(parents=True)
    (ds / "dataset.json").write_text(json.dumps(DATASET))
    return tool_dir, ds, tool_dir / "outputs" / "demo"


def sweep(cell, runs, monkeypatch, mode="ok"):
    tool_dir, ds, out = cell
    monkeypatch.setenv("FAKE_MODE", mode)
    return run_sweep.sweep(str(tool_dir), str(ds), str(out), runs, tool_cmd=[sys.executable, "tool.py"])


def test_mean_and_std_are_taken_over_all_runs(cell, monkeypatch):
    summary = sweep(cell, 4, monkeypatch)
    out = cell[2]
    assert summary["runs_requested"] == 4 and summary["runs_ok"] == 4 and summary["failures"] == []
    # runs alternate between a 3/3 and a 2/4 split; read the per-run SM back to check the aggregate
    sms = [json.loads((out / f"run_{i}" / "sm_score.json").read_text())["score"] for i in range(1, 5)]
    assert sms[0] != sms[1]
    assert summary["metrics"]["SM"]["mean"] == pytest.approx(statistics.mean(sms))
    assert summary["metrics"]["SM"]["std"] == pytest.approx(statistics.stdev(sms))
    assert summary["metrics"]["SM"]["n"] == 4
    assert json.loads((out / "metrics_mean.json").read_text()) == summary


def test_the_cell_root_holds_the_first_run_output_and_scores(cell, monkeypatch):
    sweep(cell, 2, monkeypatch)
    out = cell[2]
    assert (out / "output.json").read_text() == (out / "run_1" / "output.json").read_text()
    assert (out / "sm_score.json").exists() and (out / "metrics_summary.json").exists()


def test_a_crashed_run_is_counted_and_excluded_from_the_mean(cell, monkeypatch):
    summary = sweep(cell, 3, monkeypatch, mode="flaky")
    assert summary["runs_ok"] == 2
    assert summary["failures"] == [{"run": 2, "error": "boom"}]
    assert summary["metrics"]["SM"]["n"] == 2


def test_a_cell_where_every_run_fails_is_an_na_cell(cell, monkeypatch):
    summary = sweep(cell, 2, monkeypatch, mode="error")
    out = cell[2]
    assert summary["runs_ok"] == 0 and summary["metrics"] == {}
    assert json.loads((out / "output.json").read_text())["error"] == "boom"
    assert not (out / "sm_score.json").exists()


def test_tools_that_write_a_runs_grid_are_scored_per_grid_entry(cell, monkeypatch):
    summary = sweep(cell, 1, monkeypatch, mode="nested")
    assert summary["units"] == 2 and summary["runs_ok"] == 1
    assert summary["metrics"]["SM"]["n"] == 2
    assert (cell[2] / "run_1" / "runs" / "k2" / "sm_score.json").exists()


def test_variant_scores_and_coverage_are_aggregated(cell, monkeypatch):
    summary = sweep(cell, 2, monkeypatch)
    assert {"SM_undirected", "IFN_cross_edge", "NED_relative", "NED_triplebound"} <= set(summary["variants"])
    assert summary["coverage"]["classes"] == 6 and summary["coverage"]["assigned_mean"] == 6
