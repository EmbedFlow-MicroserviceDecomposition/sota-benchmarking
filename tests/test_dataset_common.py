import json

import pytest

from common import build_dataset


def write_project(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


GOOD = {
    "src/main/java/p/A.java": "package p; public class A { private B b = new B(); public void run() { b.go(); } }",
    "src/main/java/p/B.java": "package p; public class B { public void go() {} }",
}


def test_build_dataset_writes_schema_and_merges_usecases(tmp_path):
    ds = tmp_path / "ds"
    write_project(ds / "app", GOOD)
    (ds / "usecases.json").write_text(json.dumps({"p.A": "checkout"}))
    out = ds / "dataset.json"

    build_dataset("Demo", str(ds / "app"), str(out), "app/target/app.war", "app_kdm.xmi")

    data = json.loads(out.read_text())
    assert data["dataset"] == "Demo"
    assert data["build_path"] == "app/target/app.war"
    assert data["xmi_path"] == "app_kdm.xmi"
    assert data["usecases"] == {"p.A": "checkout"}
    assert "p.A.run" in data["methods"]
    # new B() and b.go() are two call sites
    assert {"src": "p.A", "dst": "p.B", "type": "CALL", "weight": 2.0} in data["edges"]


def test_source_path_is_relative_to_the_output_directory(tmp_path):
    ds = tmp_path / "ds"
    write_project(ds / "app", GOOD)
    out = ds / "dataset.json"

    build_dataset("Demo", str(ds / "app"), str(out), "b", "x")

    assert json.loads(out.read_text())["source_path"] == "app"


def test_parse_failure_exits_nonzero_and_writes_nothing(tmp_path):
    ds = tmp_path / "ds"
    write_project(ds / "app", {"src/main/java/p/Bad.java": "package p; public class Bad { void f( { } }"})
    out = ds / "dataset.json"

    with pytest.raises(SystemExit) as exc:
        build_dataset("Demo", str(ds / "app"), str(out), "b", "x")

    assert exc.value.code == 1
    assert not out.exists()
