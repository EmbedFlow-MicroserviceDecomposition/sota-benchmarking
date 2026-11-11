import json

from conftest import load_tool

tool = load_tool("cargo")


def test_partition_becomes_microservices_with_inner_class_separator_normalised():
    parts = {"a.B$C": 2, "a.D": 0, "a.E": 2, "a.F": 10}
    assert tool.partition_to_microservices(parts) == {
        "microservice_1": ["a.D"],
        "microservice_2": ["a.B.C", "a.E"],
        "microservice_3": ["a.F"],
    }


def test_default_grid_is_the_papers_rq3_protocol_seed_major():
    grid = tool.parse_grid("3,5,7,9,11,13", "42,43,44,45,46")
    assert len(grid) == 30
    assert grid[0] == (3, 42) and grid[1] == (5, 42) and grid[6] == (3, 43) and grid[-1] == (13, 46)


def test_a_single_run_grid():
    assert tool.parse_grid("7", "42") == [(7, 42)]


def test_dataset_without_cached_doop_facts_is_an_error_output(tmp_path):
    ds = tmp_path / "no-facts-app"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"classes": ["p.A"], "methods": {}, "edges": []}))
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "CARGO" and "Doop facts" in data["error"] and "microservices" not in data
    # a missing input is a failure to fix, not an intrinsic N/A: it must be retried once the facts exist
    assert "N/A" not in data["error"]


def test_a_dataset_with_no_java_classes_is_a_deliberate_na(tmp_path):
    ds = tmp_path / "genapp"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"dataset": "CICS Genapp", "source_path": "x"}))
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    error = json.loads((out / "output.json").read_text())["error"]
    assert "no Java classes" in error and "N/A" in error


def test_missing_dataset_json_is_an_error_output(tmp_path):
    ds = tmp_path / "jpetstore"
    ds.mkdir()
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    assert "dataset.json" in json.loads((out / "output.json").read_text())["error"]


def test_a_dataset_that_declares_bytecode_analysis_unsupported_is_a_deliberate_na(tmp_path):
    ds = tmp_path / "java17-app"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"classes": ["p.A"], "methods": {}, "edges": []}))
    (ds / "bytecode_analysis.json").write_text(json.dumps({"supported": False, "reason": "pin targets Java 17"}))
    out = tmp_path / "out"
    # even with facts present for it: the dataset's own declaration wins
    facts = tmp_path / "facts"
    facts.mkdir()
    (facts / "AnyCallGraphEdge.csv").write_text("x\n")
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out), "--facts-dir", str(facts)]) == 1
    error = json.loads((out / "output.json").read_text())["error"]
    assert "pin targets Java 17" in error and "N/A" in error


def test_a_declaration_that_says_supported_does_not_block_the_run(tmp_path):
    ds = tmp_path / "ok-app"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"classes": ["p.A"], "methods": {}, "edges": []}))
    (ds / "bytecode_analysis.json").write_text(json.dumps({"supported": True}))
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    error = json.loads((out / "output.json").read_text())["error"]
    assert "Doop facts" in error and "N/A" not in error     # got past the declaration, then failed on the missing facts


def test_an_unreadable_declaration_is_a_failure_not_an_na(tmp_path):
    ds = tmp_path / "bad-app"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"classes": ["p.A"], "methods": {}, "edges": []}))
    (ds / "bytecode_analysis.json").write_text("{not json")
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    error = json.loads((out / "output.json").read_text())["error"]
    assert "bytecode_analysis.json" in error and "N/A" not in error
