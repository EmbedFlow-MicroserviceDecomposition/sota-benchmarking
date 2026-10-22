import json

from conftest import load_tool

tool = load_tool("cogcn")


def test_membership_labels_become_numbered_microservices():
    classes = ["p.A", "p.B", "p.C", "p.D"]
    assert tool.membership_to_microservices(classes, [2, 0, 2, 1]) == {
        "microservice_1": ["p.B"], "microservice_2": ["p.D"], "microservice_3": ["p.A", "p.C"]}


def test_missing_dataset_json_is_an_error_output(tmp_path):
    ds = tmp_path / "jpetstore"
    ds.mkdir()
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "CoGCN" and "dataset.json" in data["error"]


def test_dataset_with_no_classes_is_an_error_output(tmp_path):
    ds = tmp_path / "genapp"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"dataset": "CICS Genapp", "source_path": "x"}))
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    assert "no Java classes" in json.loads((out / "output.json").read_text())["error"]


def test_k_larger_than_the_class_count_is_an_error_output(tmp_path):
    ds = tmp_path / "tiny"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"classes": ["p.A", "p.B"], "methods": {}, "edges": []}))
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out), "--k", "6"]) == 1
    assert "--k 6" in json.loads((out / "output.json").read_text())["error"]
