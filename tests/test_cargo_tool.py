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
    (ds / "dataset.json").write_text(json.dumps({"classes": [], "methods": {}, "edges": []}))
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "CARGO" and "Doop facts" in data["error"] and "microservices" not in data


def test_missing_dataset_json_is_an_error_output(tmp_path):
    ds = tmp_path / "jpetstore"
    ds.mkdir()
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    assert "dataset.json" in json.loads((out / "output.json").read_text())["error"]
