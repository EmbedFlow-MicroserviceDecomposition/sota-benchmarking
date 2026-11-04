"""CPU-only integration tests; no model downloads, CUDA or credentials required."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

@pytest.fixture
def np():
    return pytest.importorskip("numpy")


@pytest.fixture
def pd():
    return pytest.importorskip("pandas")


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


tool = load("monoembed_tool", "tools/monoembed/tool.py")
pharmacy = load("pharmacy_dataset", "datasets/pharmacy/dataset.py")


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def prepared(tmp_path):
    dataset = tmp_path / "dataset"
    write_json(dataset / "dataset.json", {
        "dataset": "Demo", "classes": ["p.B", "p.A"],
        "class_sources": {"p.B": "class B {}", "p.A": "class A {}"},
        "methods": {"p.A.go": {"class": "A", "package": "p"}},
    })
    return dataset


def test_input_order_and_missing_metadata(prepared):
    _, names, texts = tool.load_inputs(prepared)
    assert names == ["p.A", "p.B"]
    assert texts == ["class A {}", "class B {}"]
    write_json(prepared / "dataset.json", {"methods": {}})
    with pytest.raises(ValueError, match="regenerate"):
        tool.load_inputs(prepared)


@pytest.mark.parametrize("change", [
    {"classes": ["p.A", "p.A"]},
    {"classes": ["p.A"]},
    {"class_sources": {"p.A": " ", "p.B": "class B {}"}},
    {"methods": {"missing.Owner.go": {}}},
])
def test_reject_bad_input(prepared, change):
    data = json.loads((prepared / "dataset.json").read_text())
    write_json(prepared / "dataset.json", {**data, **change})
    with pytest.raises(ValueError):
        tool.load_inputs(prepared)


def test_partition_conversion():
    assert tool.to_microservices(["p.B", "p.A", "p.C"], [7, 2, 7]) == {
        "microservice_1": ["p.A"], "microservice_2": ["p.B", "p.C"]}
    for names, labels in [(["p.A"], []), (["p.A", "p.A"], [0, 1]), (["p.A"], [-1])]:
        with pytest.raises(ValueError):
            tool.to_microservices(names, labels)


def test_pinned_adapter_downloads_are_cached_and_verified(tmp_path, monkeypatch):
    import hashlib
    from io import BytesIO

    monkeypatch.delenv("MONOEMBED_ADAPTER_PATH", raising=False)
    monkeypatch.setattr(tool, "ADAPTER_CACHE", tmp_path / "cache")
    payloads = {name: ("fixture-" + name).encode() for name in tool.ADAPTER_FILES}
    monkeypatch.setattr(tool, "ADAPTER_HASHES", {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()})
    calls = []

    def fetch(url, **kwargs):
        calls.append(url)
        assert tool.ADAPTER_REVISION in url
        return BytesIO(payloads[url.rsplit("/", 1)[1]])

    monkeypatch.setattr(tool, "urlopen", fetch)
    adapter = tool.resolve_adapter()
    assert len(calls) == 3
    assert tool.resolve_adapter() == adapter
    assert len(calls) == 3
    # A corrupt cache entry is fetched again, rather than silently loaded.
    (adapter / tool.ADAPTER_FILES[0]).write_text("corrupt")
    tool.resolve_adapter()
    assert len(calls) == 4


def test_adapter_hash_mismatch_is_not_published(tmp_path, monkeypatch):
    from io import BytesIO

    monkeypatch.delenv("MONOEMBED_ADAPTER_PATH", raising=False)
    monkeypatch.setattr(tool, "ADAPTER_CACHE", tmp_path / "cache")
    monkeypatch.setattr(tool, "urlopen", lambda *args, **kwargs: BytesIO(b"corrupt"))
    with pytest.raises(ValueError, match="SHA-256"):
        tool.resolve_adapter()
    assert not list((tmp_path / "cache").iterdir())


def test_cuda_failure_prevents_model_downloads(prepared, tmp_path, monkeypatch):
    def no_cuda():
        raise RuntimeError("CUDA unavailable")

    def no_download():
        pytest.fail("A model download was attempted on a CPU-only machine")

    monkeypatch.setattr(tool, "check_cuda", no_cuda)
    monkeypatch.setattr(tool, "resolve_adapter", no_download)
    out = tmp_path / "output"
    assert tool.main(["--dataset-path", str(prepared), "--output-path", str(out)]) == 1
    assert json.loads((out / "output.json").read_text())["error"] == "CUDA unavailable"


def test_real_clustering_is_reproducible_and_finite(np):
    pytest.importorskip("sklearn")
    vectors = np.random.default_rng(9).normal(size=(16, 4))
    first, iterations = tool.cluster(vectors)
    assert first == tool.cluster(vectors)[0]
    assert len(first) == len(vectors) and all(label >= 0 for label in first)
    assert iterations > 0
    with pytest.raises(ValueError, match="finite"):
        tool.cluster(np.array([[np.nan]]))


def test_clustering_rejects_nonconvergence(monkeypatch, np):
    pytest.importorskip("sklearn")
    from sklearn.cluster import AffinityPropagation
    from sklearn.exceptions import ConvergenceWarning
    import warnings

    def fail(*args):
        warnings.warn("did not converge", ConvergenceWarning)

    monkeypatch.setattr(AffinityPropagation, "fit_predict", fail)
    with pytest.raises(ConvergenceWarning):
        tool.cluster(np.ones((3, 2)))


def test_adapter_dispatch_options_are_local_and_restored(monkeypatch):
    from types import SimpleNamespace

    calls = []

    class FakePeftModel:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            calls.append((args, kwargs))
            return "loaded"

    original = FakePeftModel.from_pretrained
    monkeypatch.setitem(sys.modules, "peft", SimpleNamespace(PeftModel=FakePeftModel))
    with tool.adapter_offloading({"device_map": "auto", "max_memory": {0: "8GiB"}}):
        assert FakePeftModel.from_pretrained("base", "adapter") == "loaded"
        FakePeftModel.from_pretrained("base", "adapter", device_map="cpu")
    assert calls[0][1]["device_map"] == "auto"
    assert calls[1][1]["device_map"] == "cpu"
    assert FakePeftModel.from_pretrained == original


def fake_adapter(tmp_path, monkeypatch):
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    for name in tool.ADAPTER_FILES:
        (adapter / name).write_text("test adapter placeholder")
    monkeypatch.setenv("MONOEMBED_ADAPTER_PATH", str(adapter))
    monkeypatch.setattr(tool, "check_cuda", lambda: None)


def test_end_to_end_contract_with_fake_inference(prepared, tmp_path, monkeypatch, np, pd):
    pytest.importorskip("sklearn")
    pytest.importorskip("pyarrow")
    fake_adapter(tmp_path, monkeypatch)
    monkeypatch.setattr(tool, "version", lambda name: "test")

    def infer(texts, adapter, output):
        assert texts == ["class A {}", "class B {}"]
        return np.array([[1.0, 0.0], [0.0, 1.0]]), {"gpu": "test"}

    monkeypatch.setattr(tool, "embed", infer)
    output = tmp_path / "output"
    assert tool.main(["--dataset-path", str(prepared), "--output-path", str(output)]) == 0
    result = json.loads((output / "output.json").read_text())
    assert result["tool"] == "MonoEmbed"
    assert sorted(c for members in result["microservices"].values() for c in members) == ["p.A", "p.B"]
    assert list(pd.read_parquet(output / "embeddings.pq").index) == ["p.A", "p.B"]
    assert set(json.loads((output / "partition.json").read_text())) == {"p.A", "p.B"}
    assert json.loads((output / "run_info.json").read_text())["converged"] is True
    # Never overwrite an earlier run, even if a new attempt fails.
    saved = (output / "output.json").read_text()
    assert tool.main(["--dataset-path", str(prepared), "--output-path", str(output)]) == 1
    assert (output / "output.json").read_text() == saved


@pytest.mark.parametrize("failure", ["inference", "shape", "convergence"])
def test_failure_writes_error_not_partition(prepared, tmp_path, monkeypatch, failure, np, pd):
    pytest.importorskip("pyarrow")
    fake_adapter(tmp_path, monkeypatch)

    def infer(*args):
        if failure == "inference":
            raise RuntimeError("GPU unavailable")
        return np.ones((1 if failure == "shape" else 2, 3)), {}

    def fail_cluster(vectors):
        raise ValueError("Clustering did not converge")

    monkeypatch.setattr(tool, "embed", infer)
    if failure == "convergence":
        monkeypatch.setattr(tool, "cluster", fail_cluster)
    output = tmp_path / "out"
    assert tool.main(["--dataset-path", str(prepared), "--output-path", str(output)]) == 1
    result = json.loads((output / "output.json").read_text())
    assert result["error"] and "microservices" not in result
    assert not (output / "partition.json").exists()


@pytest.fixture
def sources(tmp_path):
    repo = tmp_path / "app"
    source = repo / "src/main/java/p/A.java"
    source.parent.mkdir(parents=True)
    source.write_text("package p; public class A { public void go() {} class Inner {} }")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "-qm", "fixture"], check=True)
    records = [{"fullName": "p.A", "content": "public class A { public void go() {} class Inner {} }", "filePath": str(source)},
               {"fullName": "p.A$Inner", "content": "class Inner {}", "filePath": str(source)}]
    return repo, records


def test_pharmacy_preparation_and_legacy_mode(sources, tmp_path, monkeypatch):
    repo, records = sources
    monkeypatch.setattr(pharmacy, "extract_monoembed_types", lambda root: (records, "test-extractor-hash"))
    # A test source must not enter either representation in MonoEmbed mode.
    test_source = repo / "src/test/java/Test.java"
    test_source.parent.mkdir(parents=True)
    test_source.write_text("class Test { void test() {} }")
    out = tmp_path / "dataset.json"
    pharmacy.generate_universal_json("Demo", repo, out, "b", "x", monoembed=True)
    data = json.loads(out.read_text())
    assert data["classes"] == ["p.A", "p.A.Inner"]
    assert set(data["class_sources"]) == set(data["classes"])
    assert data["source_path"] == "app"
    assert data["monoembed"]["source_commit"]
    assert "p/A.java" in data["monoembed"]["source_sha256"]
    assert not any("Test" in name for name in data["methods"])
    pharmacy.generate_universal_json("Demo", str(repo), out, "b", "x")
    assert "class_sources" not in json.loads(out.read_text())


def test_preparation_builds_and_runs_only_bundled_extractor(tmp_path, monkeypatch):
    import hashlib
    from types import SimpleNamespace

    monkeypatch.setattr(pharmacy, "__file__", str(tmp_path / "datasets/pharmacy/dataset.py"))
    monkeypatch.setattr(pharmacy.shutil, "which", lambda name: "/usr/bin/" + name)
    jar = tmp_path / "tools/monoembed/extractor/target/monoembed-extractor.jar"
    calls = []

    def execute(command, **kwargs):
        calls.append(command)
        if command[0] == "mvn":
            assert kwargs["cwd"] == tmp_path / "tools/monoembed/extractor"
            jar.parent.mkdir(parents=True)
            jar.write_bytes(b"test extractor")
        else:
            assert command[:3] == ["java", "-jar", str(jar)]
        return SimpleNamespace(stdout='[{"fullName": "p.A"}]')

    monkeypatch.setattr(pharmacy.subprocess, "run", execute)
    records, digest = pharmacy.extract_monoembed_types(tmp_path / "src/main/java")
    assert records == [{"fullName": "p.A"}]
    assert digest == hashlib.sha256(b"test extractor").hexdigest()
    assert [call[0] for call in calls] == ["mvn", "java"]
    calls.clear()
    pharmacy.extract_monoembed_types(tmp_path / "src/main/java")
    assert [call[0] for call in calls] == ["java"]


@pytest.mark.parametrize("failure", ["duplicate", "empty", "outside", "missing", "parse"])
def test_preparation_rejects_invalid_types(sources, tmp_path, failure, monkeypatch):
    repo, records = sources
    monkeypatch.setattr(pharmacy, "extract_monoembed_types", lambda root: (records, "test-extractor-hash"))
    if failure == "duplicate":
        records.append(records[0])
    elif failure == "empty":
        records[0]["content"] = ""
    elif failure == "outside":
        records[0]["filePath"] = str(tmp_path / "external.java")
    elif failure == "missing":
        records.pop()
    else:
        (repo / "src/main/java/p/Bad.java").write_text("class Bad { void f( {}")
    output = tmp_path / "invalid.json"
    with pytest.raises(ValueError):
        pharmacy.generate_universal_json("Demo", repo, output, "b", "x", monoembed=True)
    assert not output.exists()


def test_all_metrics_produce_expected_artifacts(prepared, tmp_path):
    import math
    # An actual subprocess checks the repository's import paths and public CLI.
    out = tmp_path / "scores"
    write_json(out / "output.json", {"tool": "MonoEmbed", "microservices": {"m1": ["p.A"], "m2": ["p.B"]}})
    proc = subprocess.run([sys.executable, str(ROOT / "metrics/compute_all.py"),
                           "--dataset-path", str(prepared), "--output-path", str(out)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "Error computing" not in proc.stdout
    for metric in ("sm", "icp", "ifn", "ned", "bcp", "chm", "chd"):
        result = json.loads((out / f"{metric}_score.json").read_text())
        assert math.isfinite(result["score"])
