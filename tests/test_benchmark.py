import csv
import io
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import benchmark  # noqa: E402


def write_cell(root, tool, dataset, metrics=None, runs_ok=3, runs=3, coverage=None, failures=None):
    """A cell as run_sweep writes it: metrics_mean.json (+ output.json)."""
    out = root / "tools" / tool / "outputs" / dataset
    out.mkdir(parents=True)
    summary = {"tool": tool, "dataset": dataset, "runs_requested": runs, "runs_ok": runs_ok, "units": runs_ok,
               "failures": failures or [], "variants": {},
               "metrics": {k: {"mean": m, "std": s, "min": m, "max": m, "n": runs_ok}
                           for k, (m, s) in (metrics or {}).items()}}
    if coverage:
        summary["coverage"] = coverage
    (out / "metrics_mean.json").write_text(json.dumps(summary))
    return out


@pytest.fixture()
def root(tmp_path):
    for ds in ("jpetstore", "bear-board", "genapp"):
        d = tmp_path / "datasets" / ds
        d.mkdir(parents=True)
        (d / "dataset.py").write_text("")
    (tmp_path / "datasets" / "extractor").mkdir()   # not a dataset: no dataset.py
    return tmp_path


# ---------------------------------------------------------------- planning

def test_the_paper_profile_uses_the_run_counts_of_the_migration_sweep():
    assert benchmark.runs_for("chgnn", "jpetstore", "paper") == 10
    assert benchmark.runs_for("cogcn", "jpetstore", "paper") == 5
    assert benchmark.runs_for("ae-k", "jpetstore", "paper") == 3
    assert benchmark.runs_for("vae-c", "jpetstore", "paper") == 3
    assert benchmark.runs_for("vae-c", "bear-board", "paper") == 5   # the thesis averages five attempts on its own apps
    assert benchmark.runs_for("fosci", "jpetstore", "paper") == 5
    assert benchmark.runs_for("fosci", "apache-roller", "paper") == 1  # ~1-2 h per run
    assert benchmark.runs_for("cargo", "jpetstore", "paper") == 1      # the 30-run K x seed grid runs inside it


def test_the_quick_profile_is_one_run_everywhere_and_one_cargo_grid_entry():
    assert {benchmark.runs_for(t, "jpetstore", "quick") for t in benchmark.TOOLS} == {1}
    assert benchmark.tool_args("cargo", "quick") == "--k 7 --seeds 42"
    assert benchmark.tool_args("cargo", "paper") == ""
    assert benchmark.tool_args("chgnn", "quick") == ""


def test_datasets_are_the_directories_that_have_a_dataset_py(root):
    assert benchmark.list_datasets(str(root)) == ["bear-board", "genapp", "jpetstore"]


def test_the_plan_is_tool_major_and_marks_finished_cells(root):
    write_cell(root, "chgnn", "jpetstore", {"SM": (0.2, 0.01)})
    plan = benchmark.make_plan(str(root), ["chgnn", "ae-k"], ["jpetstore", "bear-board"], "paper", force=False)
    assert [(c.tool, c.dataset, c.runs, c.done) for c in plan] == [
        ("chgnn", "bear-board", 10, False), ("chgnn", "jpetstore", 10, True),
        ("ae-k", "bear-board", 3, False), ("ae-k", "jpetstore", 3, False)]


def test_a_cell_where_every_run_failed_for_a_real_reason_is_planned_again(root):
    write_cell(root, "cargo", "jpetstore", runs_ok=0, runs=1,
               failures=[{"run": 1, "error": "no Doop facts for dataset 'jpetstore' at /x"}])
    plan = benchmark.make_plan(str(root), ["cargo"], ["jpetstore"], "paper", force=False)
    assert [(c.done, c.retry) for c in plan] == [(False, True)]


def test_a_deliberate_na_cell_and_a_cell_with_results_stay_done(root):
    write_cell(root, "ae-k", "genapp", runs_ok=0, runs=1, failures=[{"run": 1, "error": "no entrypoints.txt: cell is N/A"}])
    write_cell(root, "chgnn", "jpetstore", {"SM": (0.2, 0.0)}, runs_ok=2, runs=3, failures=[{"run": 2, "error": "boom"}])
    plan = benchmark.make_plan(str(root), ["ae-k", "chgnn"], ["genapp", "jpetstore"], "paper", force=False)
    assert {(c.tool, c.dataset): (c.done, c.retry) for c in plan} == {
        ("ae-k", "genapp"): (True, False), ("ae-k", "jpetstore"): (False, False),
        ("chgnn", "genapp"): (False, False), ("chgnn", "jpetstore"): (True, False)}


def test_dry_run_says_why_a_cell_is_planned_again(root, capsys):
    write_cell(root, "cargo", "jpetstore", runs_ok=0, runs=1, failures=[{"run": 1, "error": "docker exploded"}])
    benchmark.main(["run", "--dry-run", "--tools", "cargo", "--datasets", "jpetstore"], root=str(root))
    assert "previous attempt failed" in capsys.readouterr().out


def test_force_replans_finished_cells(root):
    write_cell(root, "chgnn", "jpetstore", {"SM": (0.2, 0.01)})
    plan = benchmark.make_plan(str(root), ["chgnn"], ["jpetstore"], "paper", force=True)
    assert [c.done for c in plan] == [False]


def test_an_unknown_tool_or_dataset_is_rejected(root):
    with pytest.raises(ValueError, match="unknown tool 'nope'"):
        benchmark.make_plan(str(root), ["nope"], ["jpetstore"], "paper", force=False)
    with pytest.raises(ValueError, match="unknown dataset 'nope'"):
        benchmark.make_plan(str(root), ["chgnn"], ["nope"], "paper", force=False)


def test_dry_run_prints_the_plan_and_runs_nothing(root, capsys):
    called = []
    rc = benchmark.main(["run", "--dry-run", "--tools", "chgnn", "--datasets", "jpetstore"], root=str(root),
                        sweep_fn=lambda *a, **k: called.append(a), build_fn=lambda *a: called.append(a))
    out = capsys.readouterr().out
    assert rc == 0 and called == []
    assert "chgnn x jpetstore" in out and "10 runs" in out and "to run" in out


def test_run_builds_missing_dataset_json_then_sweeps_each_planned_cell_in_order(root):
    (root / "datasets" / "jpetstore" / "dataset.json").write_text("{}")   # already built
    built, swept = [], []

    def fake_build(ds_dir):
        built.append(Path(ds_dir).name)
        (Path(ds_dir) / "dataset.json").write_text("{}")      # like the real dataset.py

    def fake_sweep(tool_dir, dataset_dir, out_dir, runs, tool_cmd=None, extra_args=()):
        swept.append((Path(tool_dir).name, Path(dataset_dir).name, runs, list(extra_args)))
        return {"runs_ok": runs, "runs_requested": runs, "failures": [], "metrics": {"SM": {"mean": 0.1}}}

    rc = benchmark.main(["run", "--tools", "chgnn,cargo", "--datasets", "bear-board,jpetstore", "--profile", "quick"],
                        root=str(root), sweep_fn=fake_sweep, build_fn=fake_build)
    assert rc == 0
    assert built == ["bear-board"]                    # built once, and jpetstore already had its dataset.json
    assert swept == [("chgnn", "bear-board", 1, []), ("chgnn", "jpetstore", 1, []),
                     ("cargo", "bear-board", 1, ["--k", "7", "--seeds", "42"]),
                     ("cargo", "jpetstore", 1, ["--k", "7", "--seeds", "42"])]


def test_run_skips_finished_cells_and_reports_failed_ones_with_a_nonzero_exit(root, capsys):
    (root / "datasets" / "jpetstore" / "dataset.json").write_text("{}")
    write_cell(root, "chgnn", "jpetstore", {"SM": (0.2, 0.0)})

    def fake_sweep(tool_dir, dataset_dir, out_dir, runs, tool_cmd=None, extra_args=()):
        return {"runs_ok": 0, "runs_requested": runs, "failures": [{"run": 1, "error": "boom"}], "metrics": {}}

    rc = benchmark.main(["run", "--tools", "chgnn,ae-k", "--datasets", "jpetstore"], root=str(root),
                        sweep_fn=fake_sweep, build_fn=lambda d: None)
    out = capsys.readouterr().out
    assert "skip" in out and "chgnn x jpetstore" in out     # finished cell skipped
    assert "ae-k x jpetstore" in out and "boom" in out
    assert rc == 1                                         # every attempted cell failed -> nonzero


# ---------------------------------------------------------------- reading cells

def test_cell_text_formats_mean_std_and_marks_na_and_missing():
    ok = {"runs_ok": 3, "metrics": {"SM": {"mean": 0.25819, "std": 0.02013, "n": 3}}}
    single = {"runs_ok": 1, "metrics": {"SM": {"mean": 0.25819, "std": 0.0, "n": 1}}}
    assert benchmark.cell_text(ok, "SM", with_std=True) == "0.258+-0.020"
    assert benchmark.cell_text(ok, "SM", with_std=False) == "0.258"
    assert benchmark.cell_text(single, "SM", with_std=True) == "0.258"
    assert benchmark.cell_text({"runs_ok": 0, "metrics": {}}, "SM", with_std=True) == "N/A"
    assert benchmark.cell_text(None, "SM", with_std=True) == "-"
    assert benchmark.cell_text(ok, "IFN", with_std=True) == "-"          # metric not in this cell


def test_a_cell_whose_every_run_failed_for_a_real_reason_is_marked_fail_not_na():
    cell = {"runs_ok": 0, "metrics": {}, "failures": [{"run": 1, "error": "docker exploded"}]}
    na = {"runs_ok": 0, "metrics": {}, "failures": [{"run": 1, "error": "no config: cell is N/A"}]}
    assert benchmark.cell_text(cell, "SM", with_std=True) == "FAIL"
    assert benchmark.cell_text(na, "SM", with_std=True) == "N/A"


def test_ifn_is_shown_with_two_decimals():
    cell = {"runs_ok": 3, "metrics": {"IFN": {"mean": 12.3456, "std": 1.0, "n": 3}}}
    assert benchmark.cell_text(cell, "IFN", with_std=False) == "12.35"


def test_collect_reads_run_sweep_cells_and_legacy_single_run_cells(root):
    write_cell(root, "chgnn", "jpetstore", {"SM": (0.2, 0.01)}, coverage={"classes": 24, "assigned_mean": 24})
    legacy = root / "tools" / "triplet-guided-chgnn" / "outputs" / "jpetstore"
    legacy.mkdir(parents=True)
    (legacy / "output.json").write_text(json.dumps({"tool": "T", "microservices": {"m": ["a"]}}))
    (legacy / "sm_score.json").write_text(json.dumps({"metric": "SM", "score": 0.05,
                                                      "coverage": {"classes": 24, "assigned": 20}}))
    (legacy / "ned_score.json").write_text(json.dumps({"metric": "NED", "score": 0.9, "score_relative": 1.0}))
    errored = root / "tools" / "magnet" / "outputs" / "jpetstore"
    errored.mkdir(parents=True)
    (errored / "output.json").write_text(json.dumps({"error": "no xmi", "tool": "MAGNET"}))

    cells = benchmark.collect(str(root), ["chgnn", "triplet-guided-chgnn", "magnet"], ["jpetstore", "genapp"])
    assert cells[("chgnn", "jpetstore")]["metrics"]["SM"]["mean"] == 0.2
    assert cells[("triplet-guided-chgnn", "jpetstore")]["metrics"]["SM"] == {"mean": 0.05, "std": 0.0, "n": 1}
    assert cells[("triplet-guided-chgnn", "jpetstore")]["metrics"]["NED"]["mean"] == 0.9
    assert cells[("triplet-guided-chgnn", "jpetstore")]["coverage"]["assigned_mean"] == 20
    assert cells[("magnet", "jpetstore")]["runs_ok"] == 0                 # error-form output -> N/A
    assert ("chgnn", "genapp") not in cells                                # nothing there -> missing


# ---------------------------------------------------------------- rendering

def sample_cells(root):
    write_cell(root, "chgnn", "jpetstore", {"SM": (0.2581, 0.0201), "ICP": (0.3, 0.0)},
               coverage={"classes": 24, "assigned_mean": 24})
    write_cell(root, "chgnn", "bear-board", {"SM": (0.19, 0.01)}, coverage={"classes": 34, "assigned_mean": 21})
    write_cell(root, "ae-k", "jpetstore", {"SM": (0.04, 0.02)}, coverage={"classes": 24, "assigned_mean": 24})
    write_cell(root, "ae-k", "genapp", runs_ok=0, runs=1, failures=[{"run": 1, "error": "no entrypoints.txt: cell is N/A"}])
    return benchmark.collect(str(root), ["chgnn", "ae-k"], ["bear-board", "genapp", "jpetstore"])


def test_text_report_has_one_table_per_metric_with_direction_arrows(root):
    cells = sample_cells(root)
    text = benchmark.render(cells, ["chgnn", "ae-k"], ["bear-board", "genapp", "jpetstore"], ["SM", "ICP"],
                            fmt="text", with_std=True, coverage=False)
    assert "SM (higher is better)" in text and "ICP (lower is better)" in text
    sm = text.split("SM (higher is better)")[1].split("ICP (lower")[0]
    lines = [l for l in sm.splitlines() if l.strip()]
    header = next(l for l in lines if "dataset" in l)
    assert header.split() == ["dataset", "chgnn", "ae-k"]
    row = next(l for l in lines if l.startswith("jpetstore"))
    assert row.split() == ["jpetstore", "0.258+-0.020", "0.040+-0.020"]
    assert next(l for l in lines if l.startswith("genapp")).split() == ["genapp", "-", "N/A"]
    assert next(l for l in lines if l.startswith("bear-board")).split() == ["bear-board", "0.190+-0.010", "-"]


def test_markdown_report_is_a_pipe_table(root):
    cells = sample_cells(root)
    text = benchmark.render(cells, ["chgnn"], ["jpetstore"], ["SM"], fmt="markdown", with_std=False, coverage=False)
    assert "| dataset | chgnn |" in text and "| jpetstore | 0.258 |" in text and "| :-- |" in text


def test_csv_report_is_long_format_with_one_row_per_cell_and_metric(root):
    cells = sample_cells(root)
    text = benchmark.render(cells, ["chgnn", "ae-k"], ["jpetstore", "genapp"], ["SM"], fmt="csv", with_std=True,
                            coverage=False)
    rows = list(csv.DictReader(io.StringIO(text)))
    assert rows[0].keys() >= {"tool", "dataset", "metric", "mean", "std", "n", "runs_ok", "status"}
    got = {(r["tool"], r["dataset"]): r for r in rows}
    assert got[("chgnn", "jpetstore")]["mean"] == "0.2581" and got[("chgnn", "jpetstore")]["status"] == "ok"
    assert got[("ae-k", "genapp")]["status"] == "N/A"


def test_coverage_table_shows_assigned_over_total_classes(root):
    cells = sample_cells(root)
    text = benchmark.render(cells, ["chgnn", "ae-k"], ["bear-board", "jpetstore"], ["SM"], fmt="text",
                            with_std=False, coverage=True)
    cov = text.split("classes assigned")[1]
    assert next(l for l in cov.splitlines() if l.startswith("bear-board")).split() == ["bear-board", "21/34", "-"]
    assert next(l for l in cov.splitlines() if l.startswith("jpetstore")).split() == ["jpetstore", "24/24", "24/24"]


def test_report_command_prints_tables_for_the_requested_tools(root, capsys):
    sample_cells(root)
    rc = benchmark.main(["report", "--tools", "chgnn,ae-k", "--metrics", "SM"], root=str(root))
    out = capsys.readouterr().out
    assert rc == 0 and "SM (higher is better)" in out and "0.258" in out
    assert "ICP" not in out


def test_report_with_no_results_says_so_and_exits_nonzero(root, capsys):
    rc = benchmark.main(["report", "--tools", "chgnn"], root=str(root))
    assert rc == 1 and "no results" in capsys.readouterr().out
