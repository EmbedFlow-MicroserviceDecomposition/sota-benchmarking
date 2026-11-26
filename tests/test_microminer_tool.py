import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from conftest import load_tool

tool = load_tool("microminer")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "microminer"))
import microminer as mm  # noqa: E402
from partition import load_dataset, load_partition  # noqa: E402


def _make_java_dataset(tmp_path, name="demo", write_sources=True):
    ds = tmp_path / name
    src = ds / "src" / "main" / "java" / "com" / "demo"
    for sub in ("web", "service", "domain", "util"):
        (src / sub).mkdir(parents=True, exist_ok=True)

    files = {
        "com.demo.web.OrderController": (
            "src/main/java/com/demo/web/OrderController.java",
            "package com.demo.web;\npublic class OrderController { public void placeOrder() { service.createOrder(); } }\n",
        ),
        "com.demo.web.CatalogController": (
            "src/main/java/com/demo/web/CatalogController.java",
            "package com.demo.web;\npublic class CatalogController { public void listItems() { service.findCatalog(); } }\n",
        ),
        "com.demo.service.OrderService": (
            "src/main/java/com/demo/service/OrderService.java",
            "package com.demo.service;\npublic class OrderService { public void createOrder() {} }\n",
        ),
        "com.demo.service.CatalogService": (
            "src/main/java/com/demo/service/CatalogService.java",
            "package com.demo.service;\npublic class CatalogService { public void findCatalog() {} }\n",
        ),
        "com.demo.domain.OrderEntity": (
            "src/main/java/com/demo/domain/OrderEntity.java",
            "package com.demo.domain;\npublic class OrderEntity { private String orderStatus; }\n",
        ),
        "com.demo.domain.OrderItem": (
            "src/main/java/com/demo/domain/OrderItem.java",
            "package com.demo.domain;\npublic class OrderItem { private int itemQuantity; }\n",
        ),
        "com.demo.domain.ProductModel": (
            "src/main/java/com/demo/domain/ProductModel.java",
            "package com.demo.domain;\npublic class ProductModel { private String productTitle; }\n",
        ),
        "com.demo.domain.CategoryDao": (
            "src/main/java/com/demo/domain/CategoryDao.java",
            "package com.demo.domain;\npublic class CategoryDao { public void fetchCategories() {} }\n",
        ),
        "com.demo.util.DateHelper": (
            "src/main/java/com/demo/util/DateHelper.java",
            "package com.demo.util;\npublic class DateHelper { public static String formatDate() { return \"\"; } }\n",
        ),
        "com.demo.util.AppConfig": (
            "src/main/java/com/demo/util/AppConfig.java",
            "package com.demo.util;\npublic class AppConfig { public static int maxRetryCount() { return 3; } }\n",
        ),
    }

    methods = {}
    for fqn, (rel_path, code) in files.items():
        if write_sources:
            fp = ds / rel_path
            fp.write_text(code, encoding="utf-8")
        pkg, cls = fqn.rsplit(".", 1)
        methods[f"{fqn}.exec"] = {
            "id": f"{fqn}.exec",
            "class": cls,
            "package": pkg,
            "method_name": "exec",
            "return_type": "void",
            "parameters": [],
            "calls": [],
            "file_path": rel_path,
        }

    edges = [
        {"src": "com.demo.web.OrderController", "dst": "com.demo.service.OrderService", "type": "FIELD", "weight": 1.0},
        {"src": "com.demo.web.OrderController", "dst": "com.demo.service.OrderService", "type": "CALL", "weight": 3.0},
        {"src": "com.demo.web.CatalogController", "dst": "com.demo.service.CatalogService", "type": "FIELD", "weight": 1.0},
        {"src": "com.demo.service.OrderService", "dst": "com.demo.domain.OrderEntity", "type": "CALL", "weight": 2.0},
        {"src": "com.demo.domain.OrderEntity", "dst": "com.demo.domain.OrderItem", "type": "FIELD", "weight": 1.0},
        {"src": "com.demo.service.CatalogService", "dst": "com.demo.domain.ProductModel", "type": "CALL", "weight": 2.0},
        {"src": "com.demo.domain.ProductModel", "dst": "com.demo.domain.CategoryDao", "type": "FIELD", "weight": 1.0},
        {"src": "com.demo.service.OrderService", "dst": "com.demo.util.DateHelper", "type": "CALL", "weight": 1.0},
        {"src": "com.demo.util.DateHelper", "dst": "com.demo.util.AppConfig", "type": "CALL", "weight": 1.0},
    ]
    dataset = {
        "dataset": name,
        "source_path": ".",
        "classes": sorted(files),
        "methods": methods,
        "edges": edges,
    }
    (ds / "dataset.json").write_text(json.dumps(dataset, indent=2), encoding="utf-8")
    return ds, sorted(files)


def test_missing_dataset_json_writes_error_without_na(tmp_path):
    ds = tmp_path / "missing-app"
    ds.mkdir()
    out = tmp_path / "out"
    rc = tool.main(["--dataset-path", str(ds), "--output-path", str(out)])
    assert rc == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "MicroMiner"
    assert "dataset.json" in data["error"]
    assert "N/A" not in data["error"]
    assert "microservices" not in data


def test_dataset_without_java_classes_writes_na_error(tmp_path):
    ds = tmp_path / "genapp"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({"dataset": "CICS Genapp", "source_path": "cics-genapp"}))
    out = tmp_path / "out"
    rc = tool.main(["--dataset-path", str(ds), "--output-path", str(out)])
    assert rc == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "MicroMiner"
    assert "cell is N/A" in data["error"]
    assert "microservices" not in data


def test_invalid_k_writes_error(tmp_path):
    ds, _ = _make_java_dataset(tmp_path, write_sources=False)
    out = tmp_path / "out"
    rc = tool.main([
        "--dataset-path", str(ds), "--output-path", str(out),
        "--embedder", "tfidf", "--word2vec", "corpus", "--k", "99",
    ])
    assert rc == 1
    assert "--k 99" in json.loads((out / "output.json").read_text())["error"]


def test_explicit_codebert_without_sources_or_torch_fails_loudly(tmp_path, monkeypatch):
    ds_no_src, _ = _make_java_dataset(tmp_path, name="no_src", write_sources=False)
    out1 = tmp_path / "out1"
    rc1 = tool.main([
        "--dataset-path", str(ds_no_src), "--output-path", str(out1),
        "--embedder", "codebert", "--word2vec", "corpus",
    ])
    assert rc1 == 1
    assert "source files" in json.loads((out1 / "output.json").read_text())["error"]

    ds_src, _ = _make_java_dataset(tmp_path, name="with_src", write_sources=True)
    monkeypatch.setitem(sys.modules, "torch", None)
    out2 = tmp_path / "out2"
    rc2 = tool.main([
        "--dataset-path", str(ds_src), "--output-path", str(out2),
        "--embedder", "codebert", "--word2vec", "corpus",
    ])
    assert rc2 == 1
    assert "error" in json.loads((out2 / "output.json").read_text())


def test_explicit_google_news_without_gensim_fails_loudly(tmp_path, monkeypatch):
    ds, _ = _make_java_dataset(tmp_path, write_sources=False)
    monkeypatch.setitem(sys.modules, "gensim", None)
    monkeypatch.setitem(sys.modules, "gensim.downloader", None)
    out = tmp_path / "out"
    rc = tool.main([
        "--dataset-path", str(ds), "--output-path", str(out),
        "--embedder", "tfidf", "--word2vec", "google-news",
    ])
    assert rc == 1
    assert "error" in json.loads((out / "output.json").read_text())


def test_seed_labels_respect_dot_segments_and_javafx_pos_seeds():
    # Substring 'web' in 'websphere'/'weblogger' and root 'com.upachar.web' must NOT misclassify Entity/Utility.
    assert mm.derive_seed_label("com.ibm.websphere.samples.daytrader.entities.AccountDataBean") == "entity"
    assert mm.derive_seed_label("org.apache.roller.weblogger.pojos.Weblog") == "entity"
    assert mm.derive_seed_label("com.upachar.web.common.utils.DateUtil") == "utility"
    assert mm.derive_seed_label("com.upachar.web.common.dto.DrugDto") == "entity"
    assert mm.derive_seed_label("com.upachar.web.data.controller.DataController") == "application"
    # Architectural roles take priority over domain noun prefixes (Order*, Account*).
    assert mm.derive_seed_label("org.mybatis.jpetstore.web.actions.AccountActionBean") == "application"
    assert mm.derive_seed_label("org.mybatis.jpetstore.service.OrderService") == "application"
    assert mm.derive_seed_label("org.mybatis.jpetstore.mapper.OrderMapper") == "entity"
    assert mm.derive_seed_label("org.mybatis.jpetstore.web.actions.AbstractActionBean") == "utility"
    assert mm.derive_seed_label("com.acmeair.morphia.entities.CustomerImpl") == "entity"
    assert mm.derive_seed_label("com.acmeair.morphia.services.CustomerServiceImpl") == "application"
    # Authors' JavaFX-POS seed sets.
    assert mm.derive_seed_label("com.rafsan.inventory.HibernateUtil") == "utility"
    assert mm.derive_seed_label("com.rafsan.inventory.MainApp") == "application"
    assert mm.derive_seed_label("com.rafsan.inventory.pdf.PrintInvoice") == "application"
    assert mm.derive_seed_label("com.rafsan.inventory.entity.Category") == "entity"
    assert mm.derive_seed_label("com.rafsan.inventory.entity.Payment") == "entity"
    assert mm.derive_seed_label("org.pos.project.possystem.controller.ReportViewController") == "application"


def test_tiny_graph_under_four_classes_runs_cleanly(tmp_path):
    ds = tmp_path / "tiny"
    ds.mkdir()
    (ds / "dataset.json").write_text(json.dumps({
        "classes": ["p.web.A", "p.domain.B", "p.util.C"],
        "methods": {},
        "edges": [{"src": "p.web.A", "dst": "p.domain.B", "type": "CALL", "weight": 1.0}],
    }))
    out = tmp_path / "out"
    rc = tool.main(["--dataset-path", str(ds), "--output-path", str(out), "--seed", "7"])
    assert rc == 0
    output = json.loads((out / "output.json").read_text())
    assigned = [c for members in output["microservices"].values() for c in members]
    assert sorted(assigned) == ["p.domain.B", "p.util.C", "p.web.A"]
    assert json.loads((out / "run_info.json").read_text())["phase1"]["svm_used"] is False


def test_end_to_end_offline_run_and_partition_compatibility(tmp_path):
    ds, expected_classes = _make_java_dataset(tmp_path, write_sources=True)
    out = tmp_path / "out"
    rc = tool.main([
        "--dataset-path", str(ds), "--output-path", str(out),
        "--seed", "42", "--embedder", "tfidf", "--word2vec", "corpus",
    ])
    assert rc == 0

    output = json.loads((out / "output.json").read_text())
    run_info = json.loads((out / "run_info.json").read_text())
    assert output["tool"] == "MicroMiner"
    assert run_info["seed"] == 42
    assert run_info["auto_k"] is True
    assert run_info["k"] == len(output["microservices"]) == run_info["phase2_services"]["application"]
    assert run_info["embedder"] == "tfidf"
    assert run_info["word2vec"] == "corpus"
    assert run_info["java_files_resolved"] == len(expected_classes)
    assert "above_threshold_009" in run_info

    partition = load_partition(str(out), load_dataset(str(ds)))
    cov = partition.coverage()
    assert cov["classes"] == len(expected_classes)
    assert cov["assigned"] == len(expected_classes)
    assert cov["unassigned"] == 0
    assert cov["unmatched_ids"] == 0
    assert cov["conflicts"] == 0


def test_omitted_flags_fall_back_cleanly_offline_and_record_reasons(tmp_path, monkeypatch):
    ds, expected_classes = _make_java_dataset(tmp_path, write_sources=True)
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "transformers", None)
    monkeypatch.setitem(sys.modules, "gensim", None)
    monkeypatch.setitem(sys.modules, "gensim.downloader", None)
    out = tmp_path / "out"

    rc = tool.main(["--dataset-path", str(ds), "--output-path", str(out)])
    assert rc == 0
    run_info = json.loads((out / "run_info.json").read_text())
    assert run_info["embedder"] == "tfidf"
    assert run_info["embedder_fallback_reason"]
    assert run_info["word2vec"] == "corpus"
    assert run_info["word2vec_fallback_reason"]
    assert isinstance(run_info["seed"], int)
    assigned = [c for ms in json.loads((out / "output.json").read_text())["microservices"].values() for c in ms]
    assert sorted(assigned) == expected_classes


def test_k_override_and_determinism(tmp_path):
    ds, _ = _make_java_dataset(tmp_path, write_sources=True)
    out1 = tmp_path / "out1"
    out2 = tmp_path / "out2"
    out_k2 = tmp_path / "out_k2"

    for out in (out1, out2):
        assert tool.main([
            "--dataset-path", str(ds), "--output-path", str(out),
            "--seed", "11", "--embedder", "tfidf", "--word2vec", "corpus",
        ]) == 0
    assert out1.joinpath("output.json").read_text() == out2.joinpath("output.json").read_text()

    assert tool.main([
        "--dataset-path", str(ds), "--output-path", str(out_k2),
        "--seed", "11", "--k", "2", "--embedder", "tfidf", "--word2vec", "corpus",
    ]) == 0
    assert len(json.loads((out_k2 / "output.json").read_text())["microservices"]) == 2
    assert json.loads((out_k2 / "run_info.json").read_text())["auto_k"] is False


def test_fine_tune_cluster_merges_unique_max_and_skips_ties():
    services = [["A", "B"], ["C"], ["D"], ["E", "F"]]
    pair_weights = mm.aggregate_edge_weights([
        {"src": "A", "dst": "C", "type": "FIELD", "weight": 0.1},
        {"src": "B", "dst": "C", "type": "CALL", "weight": 1.0},
        {"src": "A", "dst": "D", "type": "CALL", "weight": 1.0},
        {"src": "E", "dst": "D", "type": "CALL", "weight": 1.0},
    ])
    tuned = mm.fine_tune_cluster(services, pair_weights)
    # "C" merges uniquely into ["A", "B"]; "D" has a 5.0 vs 5.0 tie so it stays singleton.
    assert ["A", "B", "C"] in tuned
    assert ["D"] in tuned
    assert ["E", "F"] in tuned


def test_utility_layer_not_fine_tuned_and_svm_guarantees_utility_in_train():
    # Ensure utility is forced into y_train regardless of seed split, and utility singletons stay separate.
    classes = [
        "com.x.web.C1", "com.x.web.C2", "com.x.service.S1", "com.x.service.S2",
        "com.x.domain.E1", "com.x.domain.E2", "com.x.domain.E3", "com.x.domain.E4",
        "com.x.util.U1", "com.x.util.U2",
    ]
    rng = np.random.default_rng(0)
    features = rng.normal(size=(len(classes), 16))
    for seed in range(5):
        layer_map, meta = mm.classify_layers_svm(classes, features, seed=seed)
        assert set(layer_map) == set(classes)
        assert meta["svm_used"] is True

    pair_weights = {("com.x.util.U1", "com.x.util.U2"): 100.0}
    typed = mm.identify_typed_services(
        {"application": ["com.x.web.C1"], "entity": ["com.x.domain.E1"], "utility": ["com.x.util.U1", "com.x.util.U2"]},
        pair_weights,
        seed=42,
    )
    # With an edge, Louvain groups U1+U2; without edges on U1/U2, fineTuneCluster is NOT run on utility.
    typed_no_edge = mm.identify_typed_services(
        {"application": ["com.x.web.C1"], "entity": ["com.x.domain.E1"], "utility": ["com.x.util.U1", "com.x.util.U2"]},
        {},
        seed=42,
    )
    assert typed_no_edge["utility"] == [["com.x.util.U1"], ["com.x.util.U2"]]
    assert len(typed["utility"]) == 1


def test_codebert_510_token_chunking_with_mocked_transformers(tmp_path, monkeypatch):
    # Exercise the exact 510-token chunked [CLS] pooling path without downloading weights.
    fake_torch = types.ModuleType("torch")
    fake_torch.long = "long"

    class _NoGrad:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    class _Tensor:
        def __init__(self, arr):
            self.arr = np.asarray(arr)
        def __getitem__(self, idx):
            return _Tensor(self.arr[idx])
        def to(self, _dev):
            return self
        def detach(self):
            return self
        def cpu(self):
            return self
        def numpy(self):
            return self.arr

    fake_torch.tensor = lambda data, dtype=None: _Tensor(data)
    fake_torch.inference_mode = lambda: _NoGrad()
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)

    seen_chunk_lengths = []

    class _FakeTokenizer:
        cls_token = "[CLS]"
        sep_token = "[SEP]"
        @classmethod
        def from_pretrained(cls, name, **kwargs):
            return cls()
        def tokenize(self, text):
            return text.split()
        def convert_tokens_to_ids(self, tokens):
            seen_chunk_lengths.append(len(tokens))
            return [len(tokens)] * len(tokens)

    class _FakeModel:
        device = "cpu"
        @classmethod
        def from_pretrained(cls, name, **kwargs):
            return cls()
        def to(self, dev):
            return self
        def eval(self):
            return self
        def __call__(self, tensor_ids):
            # Return [CLS] vector filled with the chunk length so mean pooling verifies chunking.
            seq_len = float(tensor_ids.arr.shape[1])
            out = np.full((1, int(seq_len), 4), seq_len, dtype=np.float64)
            return (_Tensor(out),)

    fake_tf = types.ModuleType("transformers")
    fake_tf.AutoTokenizer = _FakeTokenizer
    fake_tf.AutoModel = _FakeModel

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "transformers", fake_tf)

    # 600 tokens -> 2 chunks: 510 + [CLS]/[SEP] = 512, and 90 + [CLS]/[SEP] = 92; mean = (512 + 92)/2 = 302.
    embs, meta = mm.embed_codebert(
        classes=["p.LongClass", "p.EmptyClass"],
        java_texts={"p.LongClass": " ".join(["tok"] * 600), "p.EmptyClass": ""},
        methods={},
        cache_dir=tmp_path / "hf",
    )
    assert meta["model"] == "microsoft/codebert-base"
    assert embs.shape == (2, 4)
    assert seen_chunk_lengths == [512, 92, 2]
    assert np.allclose(embs[0], 302.0)
    assert np.allclose(embs[1], 2.0)
