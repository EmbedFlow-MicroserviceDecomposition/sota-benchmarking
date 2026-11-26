import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "_common"))
import vaec_tool  # noqa: E402


def make_dataset(tmp_path, name="demo", entrypoints="p.A\n"):
    ds = tmp_path / name
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({
        "classes": ["p.A", "p.B", "p.C"], "methods": {},
        "edges": [{"src": "p.A", "dst": "p.B", "type": "CALL", "weight": 1.0}]}))
    if entrypoints is not None:
        (ds / "entrypoints.txt").write_text(entrypoints)
    return ds


def stub_runner(calls):
    def run(adj, entrypoints, seed, max_paths, n_epochs, k, info):
        calls.append({"adj": adj, "entrypoints": entrypoints, "seed": seed, "k": k, "n_epochs": n_epochs})
        info["k"] = 2
        info["capped"] = False
        return {"p.A": 1, "p.B": 1, "p.C": 0}
    return run


def test_labels_become_numbered_microservices_in_cluster_order():
    assert vaec_tool.labels_to_microservices({"p.B": 10, "p.A": 9, "p.C": 9}) == {
        "microservice_1": ["p.A", "p.C"], "microservice_2": ["p.B"]}


def test_successful_run_writes_output_and_run_info(tmp_path):
    calls = []
    ds, out = make_dataset(tmp_path), tmp_path / "out"
    rc = vaec_tool.main("AE-K", stub_runner(calls), ["--dataset-path", str(ds), "--output-path", str(out), "--seed", "5"])
    assert rc == 0
    data = json.loads((out / "output.json").read_text())
    assert data == {"tool": "AE-K", "microservices": {"microservice_1": ["p.C"], "microservice_2": ["p.A", "p.B"]}}
    info = json.loads((out / "run_info.json").read_text())
    assert info == {"seed": 5, "k": 2, "capped": False}
    assert calls[0]["entrypoints"] == ["p.A"] and calls[0]["seed"] == 5 and calls[0]["n_epochs"] == 8000
    assert calls[0]["adj"]["p.A"] == ["p.B"]


def test_unseeded_runs_pick_and_record_a_seed(tmp_path):
    calls = []
    ds, out = make_dataset(tmp_path), tmp_path / "out"
    vaec_tool.main("AE-K", stub_runner(calls), ["--dataset-path", str(ds), "--output-path", str(out)])
    assert json.loads((out / "run_info.json").read_text())["seed"] == calls[0]["seed"]


def test_missing_entrypoints_is_an_error_output_and_never_runs(tmp_path):
    calls = []
    ds, out = make_dataset(tmp_path, entrypoints=None), tmp_path / "out"
    rc = vaec_tool.main("VAE-C", stub_runner(calls), ["--dataset-path", str(ds), "--output-path", str(out)])
    assert rc == 1 and calls == []
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "VAE-C" and "entrypoints.txt" in data["error"] and "microservices" not in data


def test_runner_failure_is_an_error_output(tmp_path):
    def boom(*a, **k):
        raise ValueError("no entrypoints resolved against the dependency graph")
    ds, out = make_dataset(tmp_path), tmp_path / "out"
    assert vaec_tool.main("AE-K", boom, ["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    assert "no entrypoints resolved" in json.loads((out / "output.json").read_text())["error"]


def test_paper_k_is_used_for_thesis_datasets_unless_overridden(tmp_path):
    calls = []
    ds = make_dataset(tmp_path, name="bear-board")
    vaec_tool.main("VAE-C", stub_runner(calls), ["--dataset-path", str(ds), "--output-path", str(tmp_path / "o1")],
                   paper_k={"bear-board": 5})
    vaec_tool.main("VAE-C", stub_runner(calls), ["--dataset-path", str(ds), "--output-path", str(tmp_path / "o2"), "--k", "3"],
                   paper_k={"bear-board": 5})
    assert [c["k"] for c in calls] == [5, 3]
