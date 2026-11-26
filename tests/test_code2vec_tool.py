"""Fast offline unit and integration tests for tools/code2vec (no network or real model required)."""

import io
import json
from pathlib import Path
import pickle
import sys
import tarfile

import pytest

from conftest import load_tool

tool = load_tool("code2vec")
adapter = tool.code2vec_adapter


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fake_submodule(tmp_path, monkeypatch):
    """Stand in for the tech-srl/code2vec JavaExtractor JAR without needing submodule init."""
    jar = tmp_path / "code2vec" / "JavaExtractor" / "JPredict" / "target" / "JavaExtractor-0.0.1-SNAPSHOT.jar"
    jar.parent.mkdir(parents=True, exist_ok=True)
    jar.write_bytes(b"fake-jar")
    monkeypatch.setattr(tool, "EXTRACTOR_JAR", str(jar))
    return jar


def write_synthetic_model(model_dir, np, tf, seed=0):
    """Create a tiny valid Code2Vec TF checkpoint + pickle vocabulary."""
    rng = np.random.default_rng(seed)
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    ckpt_prefix = str(model_dir / "saved_model_iter8.release")

    token_words = ["alpha", "beta", "gamma", "delta", "service", "order", "account", "marker", "interface", "execute"]
    path_strings = [
        "(NameExpr0)^(MethodDeclaration)_(NameExpr1)",
        "(VariableDeclaratorId0)^(Parameter)_(PrimitiveType1)",
        "(NameExpr0)^(BinaryExpr:plus)_(NameExpr1)",
    ]
    path_hashes = [adapter.java_string_hashcode(p) for p in path_strings]

    token_w2i = {w: i for i, w in enumerate(token_words, 1)}
    token_i2w = {i: w for w, i in token_w2i.items()}
    target_w2i = {"run": 1, "get": 2}
    target_i2w = {1: "run", 2: "get"}
    path_w2i = {h: i for i, h in enumerate(path_hashes, 1)}
    path_i2w = {i: h for h, i in path_w2i.items()}

    with open(f"{ckpt_prefix}.dict", "wb") as f:
        for w2i, i2w in ((token_w2i, token_i2w), (target_w2i, target_i2w), (path_w2i, path_i2w)):
            pickle.dump(w2i, f)
            pickle.dump(i2w, f)
            pickle.dump(len(w2i), f)

    tok_dim, path_dim, code_dim = 4, 4, 12
    words_vocab = rng.normal(0.0, 0.5, size=(len(token_words) + 1, tok_dim)).astype(np.float32)
    paths_vocab = rng.normal(0.0, 0.5, size=(len(path_hashes) + 1, path_dim)).astype(np.float32)
    transform = rng.normal(0.0, 0.5, size=(code_dim, code_dim)).astype(np.float32)
    attention = rng.normal(0.0, 0.5, size=(code_dim, 1)).astype(np.float32)

    tf.raw_ops.SaveV2(
        prefix=ckpt_prefix,
        tensor_names=["model/WORDS_VOCAB", "model/PATHS_VOCAB", "model/TRANSFORM", "model/ATTENTION"],
        shape_and_slices=["", "", "", ""],
        tensors=[
            tf.constant(words_vocab),
            tf.constant(paths_vocab),
            tf.constant(transform),
            tf.constant(attention),
        ],
    )
    return ckpt_prefix, path_strings


def test_missing_dataset_json_writes_error_without_na(tmp_path):
    ds = tmp_path / "jpetstore"
    ds.mkdir()
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "Code2Vec"
    assert "dataset.json" in data["error"]
    assert "N/A" not in data["error"]
    assert "microservices" not in data


def test_zero_java_classes_writes_na_error(tmp_path):
    ds = tmp_path / "genapp"
    ds.mkdir()
    write_json(ds / "dataset.json", {"dataset": "CICS Genapp", "source_path": "cics-genapp"})
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text())
    assert data["tool"] == "Code2Vec"
    assert "no Java classes" in data["error"]
    assert "cell is N/A" in data["error"]


def test_empty_submodule_writes_error_without_na(tmp_path, monkeypatch):
    ds = tmp_path / "tiny"
    ds.mkdir()
    write_json(ds / "dataset.json", {"classes": ["p.A", "p.B"], "methods": {}, "edges": []})
    monkeypatch.setattr(tool, "EXTRACTOR_JAR", str(tmp_path / "missing" / "JavaExtractor.jar"))
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out)]) == 1
    data = json.loads((out / "output.json").read_text())
    assert "submodule" in data["error"]
    assert "N/A" not in data["error"]


def test_k_larger_than_class_count_writes_error_without_na(tmp_path, monkeypatch):
    fake_submodule(tmp_path, monkeypatch)
    ds = tmp_path / "tiny"
    ds.mkdir()
    write_json(ds / "dataset.json", {"classes": ["p.A", "p.B"], "methods": {}, "edges": []})
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out), "--k", "5"]) == 1
    data = json.loads((out / "output.json").read_text())
    assert "--k 5" in data["error"]
    assert "N/A" not in data["error"]


def test_invalid_damping_writes_error_without_na(tmp_path, monkeypatch):
    fake_submodule(tmp_path, monkeypatch)
    ds = tmp_path / "tiny"
    ds.mkdir()
    write_json(ds / "dataset.json", {"classes": ["p.A", "p.B"], "methods": {}, "edges": []})
    out = tmp_path / "out"
    assert tool.main(["--dataset-path", str(ds), "--output-path", str(out), "--damping", "1.0"]) == 1
    data = json.loads((out / "output.json").read_text())
    assert "--damping" in data["error"]
    assert "N/A" not in data["error"]


def test_membership_to_microservices():
    assert tool.membership_to_microservices(["p.B", "p.A", "p.C"], [2, 0, 2]) == {
        "microservice_1": ["p.A"],
        "microservice_2": ["p.B", "p.C"],
    }


def test_java_string_hashcode_matches_signed_32bit():
    assert adapter.java_string_hashcode("") == "0"
    assert adapter.java_string_hashcode("a") == "97"
    assert adapter.java_string_hashcode("ab") == "3105"
    # Signed 32-bit negative wraparound matching Java String.hashCode()
    assert int(adapter.java_string_hashcode("polygenelubricants")) < 0


def test_resolve_model_files_downloads_and_reuses_cache(tmp_path, monkeypatch):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as arc:
        for fname, payload in (
            ("models/java14_model/saved_model_iter8.release.index", b"idx"),
            ("models/java14_model/saved_model_iter8.release.data-00000-of-00001", b"data"),
            ("models/java14_model/dictionaries.bin", b"dict"),
        ):
            info = tarfile.TarInfo(name=fname)
            info.size = len(payload)
            arc.addfile(info, io.BytesIO(payload))
    archive_bytes = buf.getvalue()

    calls = []

    def fake_urlopen(url, timeout=600):
        calls.append(url)
        return io.BytesIO(archive_bytes)

    monkeypatch.setattr(adapter, "urlopen", fake_urlopen)
    cache_dir = tmp_path / "cache" / "java14_model"
    ckpt1, dict1 = adapter.resolve_model_files(cache_dir=str(cache_dir))
    assert len(calls) == 1
    assert Path(f"{ckpt1}.index").is_file()
    assert Path(dict1).is_file()

    ckpt2, dict2 = adapter.resolve_model_files(cache_dir=str(cache_dir))
    assert len(calls) == 1
    assert (ckpt2, dict2) == (ckpt1, dict1)


def test_tf_checkpoint_math_matches_tensorflow_ops(tmp_path):
    np = pytest.importorskip("numpy")
    tf = pytest.importorskip("tensorflow")

    ckpt_prefix, paths = write_synthetic_model(tmp_path / "model", np, tf, seed=7)
    model = adapter.load_code2vec_model(ckpt_prefix, f"{ckpt_prefix}.dict")

    lines = [
        f"run alpha,{paths[0]},beta gamma,{paths[1]},delta",
        f"get unknownone,{paths[2]},unknowntwo",
    ]
    vecs = adapter.embed_method_lines(lines, model)
    assert vecs.shape == (2, 12)
    assert np.isfinite(vecs).all()

    # Reference computation using TensorFlow operations matching tensorflow_model.py:236-263
    for idx, line in enumerate(lines):
        src_i, path_i, dst_i, mask, _ = adapter._encode_method_line(line, model)
        ctx = tf.concat([
            tf.nn.embedding_lookup(model["words_vocab"], src_i),
            tf.nn.embedding_lookup(model["paths_vocab"], path_i),
            tf.nn.embedding_lookup(model["words_vocab"], dst_i),
        ], axis=-1)
        flat = tf.tanh(tf.matmul(ctx, model["transform"]))
        logits = tf.matmul(flat, model["attention"]) + tf.expand_dims(tf.math.log(tf.constant(mask)), axis=-1)
        attn = tf.nn.softmax(logits, axis=0)
        ref = tf.reduce_sum(flat * attn, axis=0).numpy()
        assert np.allclose(vecs[idx], ref, atol=1e-6)


def test_clustering_modes_and_silhouette_fallback():
    np = pytest.importorskip("numpy")
    pytest.importorskip("sklearn")
    from sklearn.cluster import AffinityPropagation
    from sklearn.exceptions import ConvergenceWarning
    import warnings

    # Clear 3-cluster vectors -> AffinityPropagation converges
    vectors = np.array([
        [0.0, 0.0], [0.01, 0.01], [0.0, 0.02],
        [5.0, 5.0], [5.01, 5.02], [5.02, 4.99],
        [-5.0, 5.0], [-4.99, 5.01], [-5.01, 4.98],
    ], dtype=np.float32)
    labels_ap, info_ap = tool.cluster_vectors(vectors, seed=42, damping=0.5)
    assert info_ap["clustering"] == "affinity_propagation"
    assert info_ap["k"] == 3
    assert len(labels_ap) == 9

    # Fixed --k override
    labels_k, info_k = tool.cluster_vectors(vectors, seed=42, k=2)
    assert info_k["clustering"] == "kmeans"
    assert len(set(labels_k)) == 2

    # Non-convergence -> clean silhouette fallback
    orig_fit_predict = AffinityPropagation.fit_predict

    def warn_nonconv(self, X, y=None):
        warnings.warn("did not converge", ConvergenceWarning)
        return np.zeros(len(X), dtype=int)

    try:
        AffinityPropagation.fit_predict = warn_nonconv
        labels_fb, info_fb = tool.cluster_vectors(vectors, seed=42, damping=0.5)
    finally:
        AffinityPropagation.fit_predict = orig_fit_predict

    assert info_fb["clustering"] == "silhouette_fallback"
    assert info_fb["fallback_reason"] == "affinity_propagation_did_not_converge"
    assert info_fb["k"] == 3
    assert info_fb["converged"] is False

    # Single-cluster collapse -> clean silhouette fallback
    def collapse_one(self, X, y=None):
        self.n_iter_ = 3
        return np.zeros(len(X), dtype=int)

    try:
        AffinityPropagation.fit_predict = collapse_one
        labels_c1, info_c1 = tool.cluster_vectors(vectors, seed=42, damping=0.5)
    finally:
        AffinityPropagation.fit_predict = orig_fit_predict

    assert info_c1["clustering"] == "silhouette_fallback"
    assert info_c1["fallback_reason"] == "affinity_propagation_collapsed_to_single_cluster"
    assert info_c1["k"] == 3 and len(labels_c1) == 9


def test_run_java_extractor_cli_flags(monkeypatch):
    from types import SimpleNamespace

    seen = []

    def fake_run(cmd, capture_output=True, text=True):
        seen.append(cmd)
        return SimpleNamespace(returncode=0, stdout="m a,p,b\n\n", stderr="")

    monkeypatch.setattr(adapter.subprocess, "run", fake_run)
    lines = adapter.run_java_extractor("/path/JavaExtractor.jar", "/path/Foo.java")
    assert lines == ["m a,p,b"]
    assert seen[0] == [
        "java", "-cp", "/path/JavaExtractor.jar", "JavaExtractor.App",
        "--max_path_length", "8", "--max_path_width", "2", "--file", "/path/Foo.java", "--no_hash",
    ]


def test_end_to_end_with_synthetic_checkpoint_and_fake_extractor(tmp_path, monkeypatch):
    np = pytest.importorskip("numpy")
    tf = pytest.importorskip("tensorflow")
    pytest.importorskip("sklearn")

    fake_submodule(tmp_path, monkeypatch)
    ckpt_prefix, paths = write_synthetic_model(tmp_path / "model", np, tf, seed=11)

    ds = tmp_path / "demo"
    src_root = ds / "src" / "src" / "main" / "java" / "p"
    src_root.mkdir(parents=True)
    (src_root / "OrderService.java").write_text(
        "package p; public class OrderService { public void createOrder() {} public static class Item {} }"
    )
    (src_root / "AccountService.java").write_text(
        "package p; public class AccountService { public void loadAccount() {} }"
    )
    (src_root / "MarkerInterface.java").write_text(
        "package p; public interface MarkerInterface { void execute(); }"
    )

    dataset = {
        "dataset": "Demo",
        "source_path": "src",
        "classes": [
            "p.AccountService",
            "p.MarkerInterface",
            "p.OrderService",
            "p.OrderService.Item",
        ],
        "methods": {
            "p.OrderService.createOrder": {
                "id": "p.OrderService.createOrder",
                "class": "OrderService",
                "package": "p",
                "method_name": "createOrder",
                "return_type": "void",
                "parameters": [],
                "calls": [],
                "file_path": "src/main/java/p/OrderService.java",
            },
            "p.AccountService.loadAccount": {
                "id": "p.AccountService.loadAccount",
                "class": "AccountService",
                "package": "p",
                "method_name": "loadAccount",
                "return_type": "void",
                "parameters": [],
                "calls": [],
                "file_path": "src/main/java/p/AccountService.java",
            },
            "p.MarkerInterface.execute": {
                "id": "p.MarkerInterface.execute",
                "class": "MarkerInterface",
                "package": "p",
                "method_name": "execute",
                "return_type": "void",
                "parameters": [],
                "calls": [],
                "file_path": "src/main/java/p/MarkerInterface.java",
            },
        },
        "edges": [
            {"src": "p.OrderService", "dst": "p.AccountService", "type": "CALL", "weight": 1.0}
        ],
    }
    write_json(ds / "dataset.json", dataset)

    def fake_extractor(jar_path, java_file, **kwargs):
        fname = Path(java_file).name
        if fname == "OrderService.java":
            return [f"create|order order,{paths[0]},alpha service,{paths[2]},beta"]
        if fname == "AccountService.java":
            return [f"load|account account,{paths[1]},gamma delta,{paths[0]},service"]
        return []  # MarkerInterface has no method bodies

    monkeypatch.setattr(adapter, "run_java_extractor", fake_extractor)

    out = tmp_path / "out"
    rc = tool.main([
        "--dataset-path", str(ds),
        "--output-path", str(out),
        "--model-path", ckpt_prefix,
        "--seed", "42",
        "--k", "2",
    ])
    assert rc == 0

    output_data = json.loads((out / "output.json").read_text())
    assert output_data["tool"] == "Code2Vec"
    assigned = sorted(c for members in output_data["microservices"].values() for c in members)
    assert assigned == sorted(dataset["classes"])

    run_info = json.loads((out / "run_info.json").read_text())
    assert run_info["class_count"] == 4
    assert run_info["embedding_dimensions"] == 12
    assert run_info["classes_with_methods"] == 2
    assert run_info["methodless_fallback_classes"] == 2
    assert run_info["actual_k"] == 2

    vecs = np.load(out / "class_vectors.npy")
    assert vecs.shape == (4, 12) and np.isfinite(vecs).all()

    from partition import load_partition
    part = load_partition(str(out), dataset)
    assert part.coverage() == {"classes": 4, "assigned": 4, "unassigned": 0, "unmatched_ids": 0, "conflicts": 0}
