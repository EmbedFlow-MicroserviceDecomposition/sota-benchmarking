import json
import os

import numpy as np
import pandas as pd

from conftest import load_tool

tool = load_tool("rldec")
adapter = tool.rldec_adapter if hasattr(tool, "rldec_adapter") else __import__("rldec_adapter")


def fake_submodule(tmp_path, monkeypatch):
    """Stand in for the decomp-rldec submodule, which a fresh checkout without `git submodule update` leaves empty."""
    repo = tmp_path / "decomp-rldec"
    (repo / "rldec").mkdir(parents=True)
    (repo / "rldec" / "train_model.py").write_text("", encoding="utf-8")
    monkeypatch.setattr(tool, "REPO", str(repo))
    return repo


def test_partitions_become_numbered_microservices_without_outliers_or_empty():
    raw = {
        "partition_10": ["p.D"],
        "partition_-1": ["p.Outlier"],
        "partition_-1.0": ["p.FloatOutlier"],
        "partition_2": ["p.C", "p.B"],
        "partition_1": [],
        "partition_0": ["p.A"],
    }
    assert tool.partitions_to_microservices(raw) == {
        "microservice_1": ["p.A"],
        "microservice_2": ["p.B", "p.C"],
        "microservice_3": ["p.D"],
    }


def test_missing_dataset_json_writes_non_na_error(tmp_path):
    ds = tmp_path / "jpetstore"
    ds.mkdir()
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text(encoding="utf-8"))
    assert data["tool"] == "RLDec"
    assert "dataset.json" in data["error"]
    assert "N/A" not in data["error"]
    assert "microservices" not in data


def test_dataset_with_no_classes_writes_na_error(tmp_path):
    ds = tmp_path / "genapp"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"dataset": "CICS Genapp", "source_path": "x"}), encoding="utf-8")
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    error = json.loads((out / "output.json").read_text(encoding="utf-8"))["error"]
    assert "no Java classes" in error and "N/A" in error


def test_dataset_with_fewer_than_two_classes_writes_na_error(tmp_path):
    ds = tmp_path / "singleton"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"classes": ["p.Only"], "methods": {}, "edges": []}), encoding="utf-8")
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    error = json.loads((out / "output.json").read_text(encoding="utf-8"))["error"]
    assert "fewer than 2" in error and "N/A" in error


def test_empty_submodule_writes_non_na_error(tmp_path, monkeypatch):
    empty_repo = tmp_path / "empty-rldec"
    empty_repo.mkdir()
    monkeypatch.setattr(tool, "REPO", str(empty_repo))
    ds = tmp_path / "jpetstore"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"classes": ["p.A", "p.B"], "methods": {}, "edges": []}), encoding="utf-8")
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    error = json.loads((out / "output.json").read_text(encoding="utf-8"))["error"]
    assert "submodule" in error and "N/A" not in error


def test_docker_command_runs_as_calling_user_and_mounts_repo():
    cmd = tool.docker_command("/tmp/x/repo", ["run_rldec.py", "--app", "demo"])
    assert cmd[:3] == ["docker", "run", "--rm"]
    assert cmd[cmd.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"
    assert "/tmp/x/repo:/workspace/rldec" in cmd
    assert cmd[-3:] == ["run_rldec.py", "--app", "demo"]


def test_work_folder_lives_inside_output_folder_and_is_removed_on_failure(tmp_path, monkeypatch):
    """Snap-packaged Docker cannot see /tmp (a mount from there is empty), so the temp folder must live under output."""
    fake_submodule(tmp_path, monkeypatch)
    ds = tmp_path / "jpetstore"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"classes": ["p.A", "p.B", "p.C"], "methods": {}, "edges": []}), encoding="utf-8")
    out = tmp_path / "out"
    seen = []

    class Failed:
        returncode, stdout, stderr = 1, "", "boom"

    def fake_run(repo, cli_args, runner):
        seen.append(repo)
        return Failed()

    monkeypatch.setattr(tool, "run_rldec", fake_run)
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    assert os.path.dirname(os.path.dirname(seen[0])) == str(out)
    assert not os.path.exists(os.path.dirname(seen[0]))


def test_adapter_builds_square_semantic_and_interaction_parquets_from_java_sources(tmp_path):
    src = tmp_path / "src" / "main" / "java" / "com" / "app"
    src.mkdir(parents=True)
    # 'shared' appears in 3/4 classes (> N//2 = 2), so Khaled Sellami's df filter drops it;
    # 'invoice' appears in A and B (2/4 <= 2), while 'catalog' appears in C and D (2/4 <= 2).
    (src / "OrderA.java").write_text("package com.app;\npublic class OrderA { int shared; int invoice; }", encoding="utf-8")
    (src / "OrderB.java").write_text("package com.app;\npublic class OrderB { int shared; int invoice; }", encoding="utf-8")
    (src / "ItemC.java").write_text("package com.app;\npublic class ItemC { int shared; int catalog; }", encoding="utf-8")
    (src / "ItemD.java").write_text("package com.app;\npublic class ItemD { int catalog; }", encoding="utf-8")

    dataset = {
        "dataset": "Demo",
        "source_path": ".",
        "classes": ["com.app.OrderA", "com.app.OrderB", "com.app.ItemC", "com.app.ItemD"],
        "methods": {
            "com.app.OrderA.place": {
                "method_name": "place",
                "return_type": "void",
                "parameters": [],
                "file_path": "src/main/java/com/app/OrderA.java",
            }
        },
        "edges": [
            {"src": "com.app.OrderA", "dst": "com.app.OrderB", "type": "CALL", "weight": 3.0},
            {"src": "com.app.OrderA", "dst": "com.app.OrderB", "type": "FIELD", "weight": 1.0},
        ],
    }
    out_dir = tmp_path / "rldec_data"
    info = adapter.build_rldec_inputs(dataset, str(tmp_path), str(out_dir))

    inter = pd.read_parquet(out_dir / "class_interactions.parquet")
    sem = pd.read_parquet(out_dir / "class_word_count.parquet")
    tfidf = pd.read_parquet(out_dir / "class_tfidf.parquet")

    expected = ["com.app.ItemC", "com.app.ItemD", "com.app.OrderA", "com.app.OrderB"]
    assert list(inter.index) == expected and list(inter.columns) == expected
    assert inter.shape == (4, 4)
    assert inter.loc["com.app.OrderA", "com.app.OrderB"] == 4.0

    # Square N x N semantic matrix satisfies rldec/features.py:47 both_axes=True assertion
    assert sem.shape == (4, 4)
    assert list(sem.index) == expected and list(sem.columns) == expected
    # 'shared' (df=3 > 2) dropped -> OrderB & ItemC share no kept terms; OrderA & OrderB share 'invoice'
    assert sem.loc["com.app.OrderB", "com.app.ItemC"] == 0.0
    assert sem.loc["com.app.OrderA", "com.app.OrderB"] > 0.0
    assert sem.loc["com.app.ItemC", "com.app.ItemD"] > 0.0
    assert list(tfidf.index) == expected
    assert info["java_files_matched"] == 4


def test_adapter_falls_back_to_unfiltered_bow_when_all_terms_exceed_df_threshold(tmp_path):
    dataset = {
        "classes": ["p.Alpha", "p.Beta"],
        "methods": {
            "p.Alpha.run": {"method_name": "sharedAction", "return_type": "void", "parameters": []},
            "p.Beta.run": {"method_name": "sharedAction", "return_type": "void", "parameters": []},
        },
        "edges": [],
    }
    # Force identical fallback vocabulary by naming methods identically and overriding class token test:
    # Here N=2 so threshold = max(1, 2 // 2) = 1; 'alpha' and 'beta' have df=1, 'shared'/'action' have df=2.
    # For pure identical terms test with no unique class names, test helper on two identically-stemmed classes:
    dataset_same = {
        "classes": ["a.Item", "b.Item"],
        "methods": {},
        "edges": [],
    }
    out_dir = tmp_path / "tiny"
    info = adapter.build_rldec_inputs(dataset_same, str(tmp_path), str(out_dir))
    sem = pd.read_parquet(out_dir / "class_word_count.parquet")
    assert sem.shape == (2, 2)
    assert info["filtered_vocab"] == 1
    assert np.all(sem.values > 0)


def test_mocked_run_rldec_end_to_end_writes_output_and_run_info(tmp_path, monkeypatch):
    fake_submodule(tmp_path, monkeypatch)
    ds = tmp_path / "jpetstore"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({
        "classes": ["p.Account", "p.Order", "p.Cart"],
        "methods": {
            "p.Account.login": {"method_name": "login", "return_type": "boolean", "parameters": []},
            "p.Order.submit": {"method_name": "submit", "return_type": "void", "parameters": ["p.Cart"]},
        },
        "edges": [{"src": "p.Order", "dst": "p.Cart", "type": "CALL", "weight": 2.0}],
    }), encoding="utf-8")
    out = tmp_path / "out"
    seen_data = {}

    class OK:
        returncode, stdout, stderr = 0, "mock ok\n", ""

    def fake_run(repo, cli_args, runner):
        # Verify square parquet inputs were generated inside the temp repo copy before execution
        app = cli_args[cli_args.index("--app") + 1]
        data_dir = os.path.join(repo, "data", app)
        seen_data["inter_shape"] = pd.read_parquet(os.path.join(data_dir, "class_interactions.parquet")).shape
        seen_data["sem_shape"] = pd.read_parquet(os.path.join(data_dir, "class_word_count.parquet")).shape
        seen_data["cli_args"] = cli_args
        seen_data["runner"] = runner
        raw_out = os.path.join(repo, "out")
        os.makedirs(raw_out, exist_ok=True)
        with open(os.path.join(raw_out, "decomposition.json"), "w", encoding="utf-8") as f:
            json.dump({"partition_1": ["p.Order", "p.Cart"], "partition_0": ["p.Account"]}, f)
        with open(os.path.join(raw_out, "run_meta.json"), "w", encoding="utf-8") as f:
            json.dump({"gpu_available": False, "num_gpus": 0, "train_seconds": 1.25}, f)
        return OK()

    monkeypatch.setattr(tool, "run_rldec", fake_run)
    rc = tool.main(["--dataset-path", str(ds), "--output-path", str(out), "--iterations", "5", "--runner", "uv"])
    assert rc == 0
    assert seen_data["inter_shape"] == (3, 3)
    assert seen_data["sem_shape"] == (3, 3)
    assert seen_data["runner"] == "uv"
    assert "--iterations" in seen_data["cli_args"] and "5" in seen_data["cli_args"]

    output = json.loads((out / "output.json").read_text(encoding="utf-8"))
    assert output == {
        "tool": "RLDec",
        "microservices": {
            "microservice_1": ["p.Account"],
            "microservice_2": ["p.Cart", "p.Order"],
        },
    }
    assert (out / "decomposition.json").is_file()
    assert (out / "train.log").read_text(encoding="utf-8") == "mock ok\n"
    run_info = json.loads((out / "run_info.json").read_text(encoding="utf-8"))
    assert run_info["classes"] == 3
    assert run_info["iterations"] == 5
    assert run_info["train_seconds"] == 1.25
