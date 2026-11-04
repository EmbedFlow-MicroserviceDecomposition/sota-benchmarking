# /// script
# requires-python = ">=3.11,<3.12"
# dependencies = [
#     "torch==2.4.1", "llm2vec==0.2.3", "transformers==4.44.2",
#     "tokenizers==0.19.1", "peft==0.11.1", "accelerate==0.33.0",
#     "huggingface-hub==0.24.7", "safetensors==0.4.5",
#     "setuptools==80.9.0",
#     "numpy==1.26.4", "scipy==1.14.1", "scikit-learn==1.5.2",
#     "pandas==2.2.3", "pyarrow==17.0.0", "psutil==6.0.0", "tqdm==4.66.5",
# ]
# ///
"""Local MonoEmbed inference and conversion to the SOTA benchmark contract.

Adapted from the MonoEmbed replication package and the local Pharmacy notebook.
Upstream: https://github.com/khalsel/MonoEmbed-EMSE25-RP (GPL-3.0).
This adaptation is distributed under GPL-3.0; see LICENSE in this directory.
"""

import argparse
from contextlib import contextmanager
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import random
import sys
import warnings
from urllib.request import urlopen

TOOL = "MonoEmbed"
BASE_MODEL = "McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp"
INSTRUCTION = "Given the source code, retrieve the bounded contexts; "
SEED = 42
ADAPTER_FILES = ("adapter_config.json", "adapter_model.safetensors", "llm2vec_config.json")
ADAPTER_REVISION = "c93362c7de488b9970f2c16371fe0e9b166a4e8c"
ADAPTER_CACHE = Path(__file__).resolve().parent / ".cache" / "adapter" / ADAPTER_REVISION
ADAPTER_HASHES = {
    "adapter_config.json": "a286ede3776c07b0410a7f066338c50346e8ae90e23d7c989bd135c7cbe58efe",
    "adapter_model.safetensors": "5c33f84175ee2cbafc4f0917f3c7fbecef7175d68772be8333e55ad60889ae14",
    "llm2vec_config.json": "0411696359fdaca95d479c681273f1685e609f088bae576059f6b28fcede83fe",
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    """Replace an artifact atomically so interrupted writes cannot look successful."""
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def resolve_adapter():
    """Cache only the three pinned public adapter files; no upstream clone is needed."""
    override = os.environ.get("MONOEMBED_ADAPTER_PATH")
    adapter = Path(override).expanduser().resolve() if override else ADAPTER_CACHE
    if override:
        for name in ADAPTER_FILES:
            if not (adapter / name).is_file():
                raise ValueError(f"Missing MonoEmbed adapter file: {adapter / name}")
        return adapter
    adapter.mkdir(parents=True, exist_ok=True)
    for name in ADAPTER_FILES:
        destination = adapter / name
        if destination.is_file() and sha256(destination) == ADAPTER_HASHES[name]:
            continue
        url = (f"https://raw.githubusercontent.com/khalsel/MonoEmbed-EMSE25-RP/{ADAPTER_REVISION}"
               f"/data/models/ME-llm2vec/340K/{name}")
        temporary = destination.with_name(name + ".tmp")
        print(f"Downloading pinned MonoEmbed adapter file: {name}", flush=True)
        try:
            with urlopen(url, timeout=600) as response, temporary.open("wb") as stream:
                for block in iter(lambda: response.read(1024 * 1024), b""):
                    stream.write(block)
            if sha256(temporary) != ADAPTER_HASHES[name]:
                raise ValueError(f"SHA-256 mismatch downloading adapter file {name}")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return adapter


def check_cuda():
    import torch

    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("MonoEmbed requires exactly one visible CUDA GPU; select one with CUDA_VISIBLE_DEVICES")


def load_inputs(dataset_path):
    path = Path(dataset_path) / "dataset.json"
    dataset = json.loads(path.read_text(encoding="utf-8"))
    names, sources = dataset.get("classes"), dataset.get("class_sources")
    if not isinstance(names, list) or not names or not isinstance(sources, dict):
        raise ValueError("Missing classes/class_sources: regenerate dataset.json using --monoembed; see README.md")
    if any(not isinstance(name, str) or not name.strip() or name != name.strip() for name in names):
        raise ValueError("Class FQNs must be nonempty strings without surrounding whitespace")
    if len(names) != len(set(names)) or set(names) != set(sources):
        raise ValueError("classes and class_sources must contain exactly the same unique FQNs")
    if any(not isinstance(text, str) or not text.strip() for text in sources.values()):
        raise ValueError("Every class must have nonempty source text")
    for mid in dataset.get("methods", {}):
        if mid.rsplit(".", 1)[0] not in sources:
            raise ValueError(f"Method owner is missing from class_sources: {mid}")
    names = sorted(names)
    return dataset, names, [sources[name] for name in names]


@contextmanager
def adapter_offloading(options):
    """LLM2Vec 0.2.3 omits dispatch options on its two PEFT adapter loads.

    Forward them only during model construction; never rewrite site-packages.
    This runner constructs a single model on the main thread.
    """
    from peft import PeftModel
    from unittest.mock import patch

    original = PeftModel.from_pretrained

    def load(*args, **kwargs):
        return original(*args, **{**options, **kwargs})

    with patch.object(PeftModel, "from_pretrained", side_effect=load):
        yield


def embed(texts, adapter, output_path):
    import numpy as np
    import psutil
    import torch
    from llm2vec import LLM2Vec
    from tqdm.auto import tqdm

    check_cuda()
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    total_gpu = torch.cuda.get_device_properties(0).total_memory / 1024**3
    if total_gpu < 10:
        raise RuntimeError("At least 10 GiB GPU memory is required for this offloading configuration")
    offload = Path(output_path) / "model-offload"
    offload.mkdir(exist_ok=True)
    options = {
        "device_map": "auto",
        "max_memory": {0: f"{int(total_gpu) - 2}GiB",
                       "cpu": f"{max(1, int(psutil.virtual_memory().available / 1024**3) - 4)}GiB"},
        "offload_folder": str(offload),
    }
    dtype = torch.bfloat16 if torch.cuda.get_device_capability(0)[0] >= 8 else torch.float16
    with adapter_offloading(options):
        model = LLM2Vec.from_pretrained(
            BASE_MODEL, peft_model_name_or_path=str(adapter), **options,
            offload_state_dict=True, low_cpu_mem_usage=True, torch_dtype=dtype,
            attn_implementation="eager", max_length=512, pooling_mode="mean",
        )
    model.eval()
    model.model.eval()
    input_device = model.model.get_input_embeddings().weight.device
    if input_device.type == "meta":
        input_device = torch.device("cuda:0")
    prepared = [model._convert_to_str(INSTRUCTION, text) for text in texts]
    order = np.argsort([-model._text_length(text) for text in prepared])
    batches = []
    for index in tqdm(order, desc="Embedding classes"):
        tokens = model.tokenize([model.prepare_for_tokenization(prepared[index])])
        tokens = {key: value.to(input_device) if torch.is_tensor(value) else value
                  for key, value in tokens.items()}
        with torch.inference_mode():
            vector = model.forward(tokens)
        batches.append(vector.detach().to(device="cpu", dtype=torch.float32))
    vectors = torch.cat(batches).numpy()[np.argsort(order)]
    revision = getattr(model.model.config, "_commit_hash", None)
    return vectors, {"gpu": torch.cuda.get_device_name(0), "compute_dtype": str(dtype),
                     "resolved_base_model_revision": revision}


def cluster(vectors):
    import numpy as np
    from sklearn.cluster import AffinityPropagation
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.preprocessing import scale

    if vectors.ndim != 2 or not vectors.shape[0] or not vectors.shape[1] or not np.isfinite(vectors).all():
        raise ValueError("Embeddings must be a nonempty, finite 2D matrix")
    standardized = scale(vectors, axis=0)
    if not np.isfinite(standardized).all():
        raise ValueError("Standardized embeddings are not finite")
    estimator = AffinityPropagation(damping=0.8, random_state=SEED)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ConvergenceWarning)
        labels = estimator.fit_predict(standardized)
    if estimator.n_iter_ >= estimator.max_iter or np.any(labels < 0):
        raise ValueError("Affinity Propagation did not converge")
    return labels.tolist(), int(estimator.n_iter_)


def to_microservices(names, labels):
    if len(names) != len(labels) or len(names) != len(set(names)):
        raise ValueError("Require exactly one cluster assignment per unique class")
    groups = {}
    for name, label in zip(names, labels):
        if not isinstance(label, int) or isinstance(label, bool) or label < 0:
            raise ValueError("Cluster labels must be nonnegative integers")
        groups.setdefault(label, []).append(name)
    return {f"microservice_{i}": sorted(groups[label])
            for i, label in enumerate(sorted(groups), 1)}


def run(dataset_path, output_path):
    dataset, names, texts = load_inputs(dataset_path)
    check_cuda()  # Reject CPU-only machines before downloading any model/adapter files.
    import numpy as np
    import pandas as pd

    adapter = resolve_adapter()
    vectors, device_info = embed(texts, adapter, output_path)
    vectors = np.asarray(vectors)
    if vectors.ndim != 2 or vectors.shape[0] != len(names) or not np.isfinite(vectors).all():
        raise ValueError("Embedding rows must match the complete class list and contain finite values")
    output_path = Path(output_path)
    pd.DataFrame(vectors, index=pd.Index(names, name="class"),
                 columns=[f"f{i}" for i in range(vectors.shape[1])]).to_parquet(output_path / "embeddings.pq")
    labels, iterations = cluster(vectors)
    microservices = to_microservices(names, labels)
    write_json(output_path / "partition.json", dict(zip(names, labels)))
    info = {
        "dataset": dataset.get("dataset"), "dataset_sha256": sha256(Path(dataset_path) / "dataset.json"),
        "preparation": dataset.get("monoembed", {}), "class_count": len(names),
        "base_model": BASE_MODEL, "adapter_sha256": {name: sha256(adapter / name) for name in ADAPTER_FILES},
        "adapter_upstream_revision": ADAPTER_REVISION if not os.environ.get("MONOEMBED_ADAPTER_PATH") else None,
        "instruction": INSTRUCTION, "max_length": 512, "pooling_mode": "mean", "batch_size": 1,
        "seed": SEED, "damping": 0.8, "standardization": "scale(axis=0)",
        "python": sys.version,
        "iterations": iterations, "converged": True, "embedding_dimensions": int(vectors.shape[1]),
        "packages": {name: version(name) for name in ("torch", "llm2vec", "transformers", "peft",
                      "accelerate", "numpy", "scipy", "scikit-learn", "pandas", "pyarrow")},
        **device_info,
    }
    write_json(output_path / "run_info.json", info)
    write_json(output_path / "output.json", {"tool": TOOL, "microservices": microservices})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tool: MonoEmbed local GPU runner")
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--output-path", required=True)
    args = parser.parse_args(argv)
    output = Path(args.output_path).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # An isolated run directory prevents stale results from being mistaken for this run.
    if any(output.iterdir()):
        print("Output directory must be empty; choose a new run directory", file=sys.stderr)
        return 1
    try:
        run(Path(args.dataset_path).resolve(), output)
    except Exception as exc:
        write_json(output / "output.json", {"tool": TOOL, "error": str(exc)})
        print(f"MonoEmbed failed: {exc}", file=sys.stderr)
        return 1
    print(f"MonoEmbed output: {output / 'output.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
