import json

from conftest import load_tool

tool = load_tool("chgnn")


def test_clusters_become_numbered_microservices_without_resource_nodes():
    raw = {"2": ["b.B", "tbl-res"], "0": ["a.A", "x-res", "a.A2"], "1": ["only-res"]}
    assert tool.clusters_to_microservices(raw) == {
        "microservice_1": ["a.A", "a.A2"],
        "microservice_2": ["b.B"],
    }


def test_cluster_ids_are_ordered_numerically_not_lexically():
    raw = {"10": ["c.C"], "9": ["b.B"], "0": ["a.A"]}
    assert list(tool.clusters_to_microservices(raw).values()) == [["a.A"], ["b.B"], ["c.C"]]


def test_dataset_without_a_chgnn_config_writes_an_error_output(tmp_path):
    ds = tmp_path / "no-config-app"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"dataset": "X", "methods": {}, "edges": []}))
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "CHGNN"
    assert "no CHGNN config" in data["error"]
    assert "microservices" not in data


def test_missing_dataset_json_writes_an_error_output(tmp_path):
    ds = tmp_path / "jpetstore"
    ds.mkdir()
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    assert "dataset.json" in json.loads((out / "output.json").read_text())["error"]
