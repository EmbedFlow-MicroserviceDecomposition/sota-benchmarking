import gzip
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest
from sklearn.preprocessing import OneHotEncoder

from conftest import load_tool

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "hydec"))
import hydec_adapter as adapter  # noqa: E402

tool = load_tool("hydec")

TRACE_HEADER = "traceID,order,structtype,method1,method2,m1_para,m2_para,class1,class2,m1_return,m2_return"


def _method(cls, name, params=(), ret="void", file_path=None):
    pkg, _, simple = cls.rpartition(".")
    data = {
        "id": f"{cls}.{name}",
        "class": simple,
        "package": pkg,
        "method_name": name,
        "return_type": ret,
        "parameters": list(params),
        "calls": [],
    }
    if file_path is not None:
        data["file_path"] = file_path
    return data


def make_dataset(tmp_path, name="demo", with_java=False, with_trace=False, classes=None):
    ds = tmp_path / name
    ds.mkdir(parents=True, exist_ok=True)
    if classes is None:
        classes = [
            "p.OrderController",
            "p.OrderService",
            "p.OrderRepo",
            "p.BillingService",
            "p.BillingRepo",
            "p.Invoice",
        ]
    methods = {}
    if with_java:
        src_root = ds / "src-root"
        src_dir = src_root / "src" / "main" / "java" / "p"
        src_dir.mkdir(parents=True)
        sources = {
            "p.OrderController": "package p;\nimport java.util.List;\npublic class OrderController { public void placeCustomerOrder() {} }\n",
            "p.OrderService": "package p;\npublic class OrderService { public void createCustomerOrder() {} }\n",
            "p.OrderRepo": "package p;\npublic interface OrderRepo { void saveCustomerOrder(); }\n",
            "p.BillingService": "package p;\npublic class BillingService { public void chargePaymentInvoice() {} }\n",
            "p.BillingRepo": "package p;\npublic class BillingRepo { public void storePaymentInvoice() {} }\n",
            "p.Invoice": "package p;\npublic class Invoice { private double paymentAmount; }\n",
        }
        for cls in classes:
            simple = cls.rsplit(".", 1)[-1]
            rel = f"src/main/java/p/{simple}.java"
            (src_dir / f"{simple}.java").write_text(sources.get(cls, f"package p;\npublic class {simple} {{}}\n"))
            # Leave p.Invoice without methods to test source-root fallback for method-less classes.
            if cls != "p.Invoice":
                m = _method(cls, f"handle{simple}", ["String"], "void", file_path=rel)
                methods[m["id"]] = m
        source_path = "src-root"
    else:
        for cls in classes:
            simple = cls.rsplit(".", 1)[-1]
            m = _method(cls, f"process{simple}", [simple], "void")
            methods[m["id"]] = m
        source_path = "missing-src"

    edges = []
    if len(classes) >= 6:
        edges = [
            {"src": "p.OrderController", "dst": "p.OrderService", "type": "CALL", "weight": 3.0},
            {"src": "p.OrderService", "dst": "p.OrderRepo", "type": "FIELD", "weight": 2.0},
            {"src": "p.OrderRepo", "dst": "p.OrderService", "type": "CALL", "weight": 1.0},
            {"src": "p.BillingService", "dst": "p.BillingRepo", "type": "CALL", "weight": 4.0},
            {"src": "p.BillingRepo", "dst": "p.Invoice", "type": "FIELD", "weight": 2.0},
            {"src": "p.BillingService", "dst": "p.Invoice", "type": "CALL", "weight": 2.0},
            {"src": "p.OrderService", "dst": "p.OrderService", "type": "CALL", "weight": 5.0},
        ]

    payload = {
        "dataset": name,
        "source_path": source_path,
        "classes": list(classes),
        "methods": methods,
        "edges": edges,
    }
    (ds / "dataset.json").write_text(json.dumps(payload), encoding="utf-8")

    if with_trace:
        rows = [
            "0,0,null,p.OrderController.handle,p.OrderService.handle,,,p.OrderController,p.OrderService,,",
            "0,1,null,p.OrderService.handle,p.OrderRepo.handle,,,p.OrderService,p.OrderRepo,,",
            "1,0,null,p.BillingService.handle,p.BillingRepo.handle,,,p.BillingService,p.BillingRepo,,",
            "1,1,null,p.BillingService.handle,p.BillingService.handle,,,p.BillingService,p.BillingService,,",
            "1,2,null,p.Proxy$Accessor.call,p.BillingRepo.handle,,,p.Proxy$Accessor,p.BillingRepo,,",
        ]
        with gzip.open(ds / "fosci_trace.csv.gz", "wt", encoding="utf-8") as f:
            f.write(TRACE_HEADER + "\n" + "\n".join(rows) + "\n")
    return ds


def fake_submodule(tmp_path, monkeypatch, layers=None, recorder=None):
    """Stand in for tools/hydec/decomp-hydec when testing isolated tool orchestration."""
    repo = tmp_path / "fake-decomp-hydec"
    hydec_dir = repo / "hydec"
    hydec_dir.mkdir(parents=True)
    (hydec_dir / "__init__.py").write_text("from .hydec import generate_decomposition\n")

    layers_json = json.dumps(layers) if layers is not None else "None"
    code = f"""
import json
import os

CALLS = []

def generate_decomposition(app, app_repo=None, decomp_approach="hyDec", hyperparams_path=None,
                           structural_path=None, semantic_path=None, dynamic_path=None,
                           include_metadata=False, save_output=False, granularity="class",
                           is_distributed=False, use_parsing_module=True, data_path=None, *args, **kwargs):
    with open(os.path.join(semantic_path, "class_names.json"), encoding="utf-8") as f:
        atoms = json.load(f)
    CALLS.append({{
        "app": app,
        "decomp_approach": decomp_approach,
        "hyperparams_path": hyperparams_path,
        "structural_path": structural_path,
        "semantic_path": semantic_path,
        "dynamic_path": dynamic_path,
        "include_metadata": include_metadata,
        "save_output": save_output,
        "granularity": granularity,
        "use_parsing_module": use_parsing_module,
        "data_path": data_path,
    }})
    out_layers = {layers_json}
    if out_layers is None:
        out_layers = [list(range(len(atoms))), [i // 2 for i in range(len(atoms))]]
    return out_layers[-1], out_layers, atoms, {{"exec_time": {{"total": 0.01}}}}
"""
    (hydec_dir / "hydec.py").write_text(code, encoding="utf-8")
    monkeypatch.setattr(tool, "REPO", str(repo))
    if recorder is not None:
        recorder["repo"] = repo
    return repo


# ---------------------------------------------------------------- adapter tests

def test_adapter_builds_directed_structural_matrix_and_ignores_self_loops(tmp_path):
    ds = make_dataset(tmp_path, with_java=True)
    dataset = json.loads((ds / "dataset.json").read_text())
    out = tmp_path / "inputs"

    info = adapter.build_hydec_inputs(dataset, str(ds), str(out))
    names = json.loads((out / "structural" / "class_names.json").read_text())
    calls = np.load(out / "structural" / "class_calls.npy")

    assert names == sorted(dataset["classes"])
    assert calls.shape == (6, 6)
    idx = {c: i for i, c in enumerate(names)}
    assert calls[idx["p.OrderController"], idx["p.OrderService"]] == pytest.approx(3.0)
    assert calls[idx["p.OrderService"], idx["p.OrderRepo"]] == pytest.approx(2.0)
    assert calls[idx["p.OrderRepo"], idx["p.OrderService"]] == pytest.approx(1.0)
    assert np.all(np.diag(calls) == 0.0)
    assert info["classes"] == 6 and info["edges"] == 6


def test_adapter_resolves_java_sources_including_methodless_classes(tmp_path):
    ds = make_dataset(tmp_path, with_java=True)
    dataset = json.loads((ds / "dataset.json").read_text())
    out = tmp_path / "inputs"

    info = adapter.build_hydec_inputs(dataset, str(ds), str(out))
    tfidf = np.load(out / "semantic" / "class_tfidf.npy")
    sem_names = json.loads((out / "semantic" / "class_names.json").read_text())
    str_names = json.loads((out / "structural" / "class_names.json").read_text())

    assert sem_names == str_names
    assert tfidf.shape[0] == 6 and tfidf.shape[1] > 0
    assert info["java_files_resolved"] == 6
    assert info["fallback_classes"] == 0


def test_adapter_falls_back_to_dataset_json_tokens_when_java_sources_missing(tmp_path):
    ds = make_dataset(tmp_path, with_java=False)
    dataset = json.loads((ds / "dataset.json").read_text())
    out = tmp_path / "inputs"

    info = adapter.build_hydec_inputs(dataset, str(ds), str(out))
    tfidf = np.load(out / "semantic" / "class_tfidf.npy")

    assert info["java_files_resolved"] == 0
    assert info["fallback_classes"] == 6
    assert tfidf.shape[0] == 6 and tfidf.shape[1] > 0
    assert np.all(np.linalg.norm(tfidf, axis=1) > 0)


def test_adapter_handles_all_noise_semantic_tokens_without_crashing(tmp_path):
    ds = make_dataset(tmp_path, with_java=False, classes=["p.List", "p.Map"])
    dataset = json.loads((ds / "dataset.json").read_text())
    dataset["methods"] = {}
    out = tmp_path / "inputs"

    info = adapter.build_hydec_inputs(dataset, str(ds), str(out))
    tfidf = np.load(out / "semantic" / "class_tfidf.npy")

    assert tfidf.shape == (2, 1)
    assert np.all(tfidf == 0.0)
    assert info["semantic_vocab"] == 0


def test_adapter_builds_dynamic_matrix_filtering_non_project_classes(tmp_path):
    ds = make_dataset(tmp_path, with_java=False, with_trace=True)
    dataset = json.loads((ds / "dataset.json").read_text())
    out = tmp_path / "inputs"

    info = adapter.build_hydec_inputs(
        dataset, str(ds), str(out), approach="hyDec", trace_path=str(ds / "fosci_trace.csv.gz")
    )
    dyn_names = json.loads((out / "dynamic" / "class_names.json").read_text())
    dyn_calls = np.load(out / "dynamic" / "class_calls.npy")

    assert dyn_names == ["p.BillingRepo", "p.BillingService", "p.OrderController", "p.OrderRepo", "p.OrderService"]
    assert "p.Proxy$Accessor" not in dyn_names
    idx = {c: i for i, c in enumerate(dyn_names)}
    assert dyn_calls[idx["p.OrderController"], idx["p.OrderService"]] == pytest.approx(1.0)
    assert dyn_calls[idx["p.BillingService"], idx["p.BillingRepo"]] == pytest.approx(1.0)
    assert np.all(np.diag(dyn_calls) == 0.0)
    assert info["dynamic_classes"] == 5 and info["dynamic_calls"] == 3


# ---------------------------------------------------------------- shims & helpers

def test_onehotencoder_compat_shim_works_on_modern_sklearn():
    tool.patch_onehotencoder()
    enc = OneHotEncoder(sparse=False, dtype=int)
    arr = enc.fit_transform(np.array([[0], [1], [0]]))
    assert arr.shape == (3, 2)
    assert "sparse_output" in enc.get_params()


def test_select_layer_falls_back_when_final_layer_collapses():
    layers = [[0, 1, 2, 3], [0, 0, 1, 1], [0, 0, 0, 0]]
    labels, idx, fell_back = tool.select_layer(layers)
    assert labels == [0, 0, 1, 1] and idx == 1 and fell_back is True


def test_clusters_to_microservices_promotes_outliers_to_singletons():
    ms, outliers = tool.clusters_to_microservices(["p.C", "p.A", "p.B", "p.D"], [2, -1, 0, -1])
    assert outliers == 2
    assert ms == {
        "microservice_1": ["p.B"],
        "microservice_2": ["p.C"],
        "microservice_3": ["p.A"],
        "microservice_4": ["p.D"],
    }


# ---------------------------------------------------------------- error contract

def test_missing_dataset_json_is_retriable_error(tmp_path):
    ds = tmp_path / "jpetstore"
    ds.mkdir()
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "HyDec"
    assert "dataset.json" in data["error"]
    assert "N/A" not in data["error"]
    assert "microservices" not in data


def test_zero_java_classes_writes_deliberate_na_even_without_submodule(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "REPO", str(tmp_path / "missing-submodule"))
    ds = tmp_path / "genapp"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"dataset": "CICS Genapp", "source_path": "cics-genapp"}))
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "HyDec" and "cell is N/A" in data["error"]


def test_empty_submodule_writes_retriable_error(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "REPO", str(tmp_path / "empty-decomp-hydec"))
    ds = make_dataset(tmp_path)
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "HyDec" and "submodule" in data["error"]
    assert "N/A" not in data["error"]


def test_hydec_approach_without_trace_writes_retriable_error(tmp_path, monkeypatch):
    fake_submodule(tmp_path, monkeypatch)
    ds = make_dataset(tmp_path, with_trace=False)
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out), "--approach", "hyDec"]) == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "HyDec" and "fosci_trace.csv.gz" in data["error"]
    assert "N/A" not in data["error"]


# ---------------------------------------------------------------- tool runs

def test_tool_with_fake_submodule_handles_collapsed_layer_and_cleans_workdir(tmp_path, monkeypatch):
    collapsed_layers = [
        [0, 1, 2, 3, 4, 5],
        [0, 0, 0, 1, 1, 2],
        [0, 0, 0, 0, 0, 0],
    ]
    fake_submodule(tmp_path, monkeypatch, layers=collapsed_layers)
    ds = make_dataset(tmp_path, with_java=True)
    out = tmp_path / "out"

    rc = tool.main([
        "--dataset-path", str(ds),
        "--output-path", str(out),
        "--epsilon", "0.5",
        "--min-samples", "2",
        "--strategy", "sequential",
    ])
    assert rc == 0
    data = json.loads((out / "output.json").read_text())
    run_info = json.loads((out / "run_info.json").read_text())
    layers_doc = json.loads((out / "layers.json").read_text())

    assert data["tool"] == "HyDec"
    assert len(data["microservices"]) == 3
    assert sorted(c for ms in data["microservices"].values() for c in ms) == sorted(
        json.loads((ds / "dataset.json").read_text())["classes"]
    )
    assert run_info["selected_layer"] == 1
    assert run_info["total_layers"] == 3
    assert run_info["collapsed_fallback"] is True
    assert run_info["approach"] == "hierDec"
    assert run_info["epsilon"] == pytest.approx(0.5)
    assert run_info["strategy"] == "sequential"
    assert layers_doc["selected_layer"] == 1
    assert not any(p.name.startswith("work-") for p in out.iterdir())


def test_end_to_end_hierdec_and_hydec_partition_all_classes(tmp_path, monkeypatch):
    """Run real decomp-hydec when initialized, otherwise exercise the same contract via fake_submodule."""
    real_present = os.path.isfile(os.path.join(tool.REPO, "hydec", "hydec.py"))
    if not real_present:
        fake_submodule(tmp_path, monkeypatch, layers=[
            [0, 1, 2, 3, 4, 5],
            [0, 0, 0, 1, 1, 1],
        ])

    ds = make_dataset(tmp_path, with_java=True, with_trace=True)
    classes = sorted(json.loads((ds / "dataset.json").read_text())["classes"])

    for approach, out_name in (("hierDec", "out-hier"), ("hyDec", "out-hy")):
        out = tmp_path / out_name
        rc = tool.main([
            "--dataset-path", str(ds),
            "--output-path", str(out),
            "--approach", approach,
        ])
        assert rc == 0
        output = json.loads((out / "output.json").read_text())
        info = json.loads((out / "run_info.json").read_text())
        assigned = sorted(c for members in output["microservices"].values() for c in members)
        assert output["tool"] == "HyDec"
        assert assigned == classes
        assert info["approach"] == approach
        assert info["n_microservices"] == len(output["microservices"])
        if real_present:
            assert info["total_layers"] >= 2
        if approach == "hyDec":
            assert info["dynamic_classes"] == 5
