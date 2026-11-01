import json
import os

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


def test_the_container_runs_as_the_calling_user_so_the_files_it_writes_can_be_cleaned_up():
    cmd = tool.docker_command("/tmp/x/repo", ["run_chgnn.py", "--k", "3"])
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert cmd[cmd.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert "/tmp/x/repo:/workspace/chgnn" in cmd
    assert cmd[-3:] == ["run_chgnn.py", "--k", "3"]


def test_the_work_folder_lives_inside_the_output_folder_so_snap_docker_can_mount_it(tmp_path, monkeypatch):
    """Snap-packaged Docker cannot see /tmp (a mount from there is empty), so the temp folder must not default to it."""
    ds = tmp_path / "jpetstore"                       # a name with a CHGNN config
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"classes": ["p.A"], "methods": {}, "edges": []}))
    out = tmp_path / "out"
    seen = []

    def fake_prepare(work, slug, dataset, config_dir, entrypoints_file):
        seen.append(work)
        raise ValueError("stop here")

    monkeypatch.setattr(tool, "prepare_repo", fake_prepare)
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    assert os.path.dirname(seen[0]) == str(out)
    assert not os.path.exists(seen[0])                # and it is removed afterwards
