import json
import subprocess
import sys
from pathlib import Path

import pytest

COMPUTE_ALL = Path(__file__).resolve().parents[1] / "metrics" / "compute_all.py"


def method(cls_fqn, name, calls=()):
    pkg, _, simple = cls_fqn.rpartition(".")
    return {"id": f"{cls_fqn}.{name}", "class": simple, "package": pkg, "method_name": name,
            "return_type": "String", "parameters": ["int"], "calls": list(calls)}


def write_case(tmp_path, microservices):
    ds, out = tmp_path / "ds", tmp_path / "out"
    ds.mkdir(parents=True), out.mkdir(parents=True)
    methods = {m["id"]: m for m in (
        method("p.A", "run", ["p.B.go", "p.C.go"]), method("p.B", "go"), method("p.C", "go"),
        method("p.D", "idle"))}
    edges = [{"src": "p.A", "dst": "p.B", "type": "CALL", "weight": 1.0},
             {"src": "p.A", "dst": "p.C", "type": "CALL", "weight": 1.0},
             {"src": "p.B", "dst": "p.C", "type": "FIELD", "weight": 1.0}]
    (ds / "dataset.json").write_text(json.dumps({"methods": methods, "edges": edges, "usecases": {"A": ["u1"], "B": ["u2"]}}))
    (out / "output.json").write_text(json.dumps({"tool": "T", "microservices": microservices}))
    return ds, out


def run(ds, out):
    return subprocess.run([sys.executable, str(COMPUTE_ALL), "--dataset-path", str(ds), "--output-path", str(out)],
                          capture_output=True, text=True)


def score(out, name):
    return json.loads((out / f"{name}_score.json").read_text())


def test_single_cluster_scores_every_metric_without_crashing(tmp_path):
    ds, out = write_case(tmp_path, {"ms1": ["p.A", "p.B", "p.C", "p.D"]})
    proc = run(ds, out)
    assert proc.returncode == 0, proc.stderr
    assert "Error computing" not in proc.stdout
    assert score(out, "icp")["score"] == 0.0
    for name in ("sm", "icp", "ifn", "ned", "bcp", "chm", "chd"):
        assert (out / f"{name}_score.json").exists(), name


def test_partial_partition_reports_unassigned_classes(tmp_path):
    ds, out = write_case(tmp_path, {"ms1": ["p.A"], "ms2": ["p.B", "org.ghost.Ghost"]})
    proc = run(ds, out)
    assert proc.returncode == 0, proc.stderr
    cov = score(out, "sm")["coverage"]
    assert cov == {"classes": 4, "assigned": 2, "unassigned": 2, "unmatched_ids": 1, "conflicts": 0}
    assert score(out, "icp")["score"] == 1.0  # the only scorable call edge A->B crosses; A->C has no cluster


def test_error_output_is_not_scored_and_exits_nonzero(tmp_path):
    ds, out = write_case(tmp_path, {"ms1": ["p.A"]})
    (out / "output.json").write_text(json.dumps({"error": "docker exploded", "tool": "T"}))
    proc = run(ds, out)
    assert proc.returncode == 1
    assert "docker exploded" in proc.stderr
    assert not (out / "sm_score.json").exists()
    assert not (out / "metrics_summary.json").exists()


def test_method_level_output_matches_equivalent_class_level_output(tmp_path):
    ds, out = write_case(tmp_path, {"ms1": ["p.A.run", "p.B.go"], "ms2": ["p.C.go", "p.D.idle"]})
    run(ds, out)
    method_scores = {n: score(out, n)["score"] for n in ("sm", "icp", "ifn")}
    ds2, out2 = write_case(tmp_path / "second", {"ms1": ["p.A", "p.B"], "ms2": ["p.C", "p.D"]})
    run(ds2, out2)
    assert method_scores == {n: score(out2, n)["score"] for n in ("sm", "icp", "ifn")}


def test_a_metric_that_raises_fails_compute_all_but_the_other_scores_are_still_written(tmp_path, monkeypatch):
    import compute_all

    ds, out = write_case(tmp_path, {"ms1": ["p.A", "p.B"], "ms2": ["p.C", "p.D"]})

    def broken(*args, **kwargs):
        raise ValueError("chm exploded")

    monkeypatch.setattr(compute_all, "evaluate_chm", broken)
    with pytest.raises(compute_all.MetricsIncomplete, match="CHM: chm exploded"):
        compute_all.compute_all_metrics(str(ds), str(out))
    summary = json.loads((out / "metrics_summary.json").read_text())
    assert "SM" in summary and "CHM" not in summary
    assert (out / "sm_score.json").exists()
