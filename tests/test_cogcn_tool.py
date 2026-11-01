import json
import os

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


def test_the_container_runs_as_the_calling_user_so_the_files_it_writes_can_be_cleaned_up():
    cmd = tool.docker_command("/tmp/x/repo", ["run_cogcn.py", "--k", "3"])
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert cmd[cmd.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert "/tmp/x/repo:/workspace/cogcn" in cmd
    assert cmd[-3:] == ["run_cogcn.py", "--k", "3"]


def test_the_work_folder_lives_inside_the_output_folder_so_snap_docker_can_mount_it(tmp_path, monkeypatch):
    ds = tmp_path / "tiny"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"classes": ["p.A", "p.B", "p.C", "p.D", "p.E", "p.F"], "methods": {}, "edges": []}))
    out = tmp_path / "out"
    seen = []

    class Failed:
        returncode, stdout, stderr = 1, "", "stop here"

    def fake_train(repo, data_arg, k, runner):
        seen.append(repo)
        return Failed()

    monkeypatch.setattr(tool, "run_train", fake_train)
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    assert os.path.dirname(os.path.dirname(seen[0])) == str(out)      # <out>/<work dir>/cogcn
    assert not os.path.exists(os.path.dirname(seen[0]))
