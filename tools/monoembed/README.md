# MonoEmbed

Local class-level inference with the ME-llm2vec 340K adapter, followed by standardized
embeddings and Affinity Propagation. The public runner accepts exactly
`--dataset-path` and `--output-path`, matching this branch's tool contract.

## Prepare inputs and model

Everything needed for source preparation and inference is included here. No
other personal project, cloned MonoEmbed repository, copied JAR, or copied adapter
is required. Dependencies and model artifacts are downloaded from their official
upstreams on the server.

The server needs Git, `uv`, JDK 17, Maven, and a working CUDA driver. The runner
uses Python 3.11, exactly one visible GPU with at least 10 GiB VRAM, CPU RAM for
model offloading, and disk space for the 8B base model and offload files. Model
loading can require substantial host memory. Python dependencies are pinned
inline; the source extractor's dependencies are declared in its bundled POM.

From a fresh clone on the GPU server, prepare Pharmacy:

```bash
git clone --branch migrate/monoembed \
  https://github.com/EmbedFlow-MicroserviceDecomposition/sota-benchmarking.git
cd sota-benchmarking

git -c 'url.https://github.com/.insteadOf=git@github.com:' \
  submodule update --init datasets/pharmacy/pharmacy

(cd datasets/pharmacy && uv run dataset.py --monoembed)
```

The final command builds the bundled Spoon extractor on first use and writes the
existing generated `dataset.json`. See [Pharmacy preparation](../../datasets/pharmacy/README.md#monoembed-inputs).
Other datasets need the same `classes` and `class_sources` fields; their legacy
method-only adapters are not automatically converted.

At inference time, the runner fetches only these three adapter files from
`khalsel/MonoEmbed-EMSE25-RP` at commit
`c93362c7de488b9970f2c16371fe0e9b166a4e8c`:

```text
adapter_config.json
adapter_model.safetensors
llm2vec_config.json
```

Files are SHA-256 checked and cached in `tools/monoembed/.cache/`, which is ignored
by Git. No upstream repository is cloned. `MONOEMBED_ADAPTER_PATH` remains an
optional override for an already available adapter directory; it is not needed
for the default server workflow.

The base model is `McGill-NLP/LLM2Vec-Meta-Llama-3-8B-Instruct-mntp`. Use Hugging
Face's normal cache and `HF_TOKEN` or saved login; accept any required upstream
Llama access terms. The GPU check runs before any model/adapter download. Python
package installation by `uv` can still occur before that check. No base-model or
adapter download is required to prepare source inputs or run the CPU tests.

## Run and score

From the repository root, with a prepared Pharmacy `dataset.json`:

```bash
export CUDA_VISIBLE_DEVICES=0
export HF_HOME="$PWD/tools/monoembed/.cache/huggingface"
export HF_HUB_CACHE="$HF_HOME/hub"
export TRANSFORMERS_CACHE="$HF_HUB_CACHE"
mkdir -p "$HF_HUB_CACHE"
read -rsp "Hugging Face token: " HF_TOKEN
export HF_TOKEN
printf '\n'
uv run tools/monoembed/tool.py \
  --dataset-path datasets/pharmacy \
  --output-path tools/monoembed/outputs/pharmacy/run_01
```

The cache variables above keep model files in the repository's writable, ignored
cache directory. For a different writable server volume, change `HF_HOME` and
derive the other two variables from it. Run these exports inside the tmux session
before starting the tool. `setuptools` is explicitly pinned because the inference
dependency stack requires it and isolated `uv` environments may not include it.
After a failed attempt, use a fresh output directory such as `run_02`; the verified
adapter cache is reused.

After a successful tool exit, score the same directory:

```bash
uv run metrics/compute_all.py \
  --dataset-path datasets/pharmacy \
  --output-path tools/monoembed/outputs/pharmacy/run_01
```

Check for all seven `*_score.json` files and for `Error computing` messages: the
existing metrics runner catches individual errors and can exit zero with missing
scores. Never score a failed tool run; its `output.json` contains an `error` rather
than a partition. BCP requires meaningful class-to-use-case mappings in
`usecases.json` or `dataset.json`; an empty mapping produces a zero that does not
establish business-context purity. Existing static call extraction is approximate.
NED uses this repository's higher-is-better definition, unlike the complement
described by the old Pharmacy notebook.

## Protocol and artifacts

Each invocation embeds classes once and clusters once. Classes are sorted by FQN;
length-based inference batches are reordered back to that order. Settings match
the Pharmacy notebook: seed 42, batch size 1, mean pooling, maximum length 512,
instruction `Given the source code, retrieve the bounded contexts; `, dimension-wise
`scale(axis=0)`, and Affinity Propagation damping 0.8. GPU floating-point operations
are not guaranteed bit-for-bit identical across hardware. This is a single run,
not the notebook's ten-seed experiment.

The output directory must be empty or new. It contains:

- `output.json`: `{"tool": "MonoEmbed", "microservices": {"microservice_1": ["pkg.Class"]}}`.
- `partition.json`: raw class-to-integer-label assignments.
- `embeddings.pq`: float32 vectors indexed by class FQN.
- `run_info.json`: input and adapter hashes, preparation provenance, runtime
  versions, model identity, pinned adapter revision, and clustering convergence information.
- `model-offload/`: runtime offload files, if needed by Accelerate.

All artifacts stay under the already ignored `outputs/` directory. A failed run
returns nonzero and writes an error-form `output.json`; intermediate artifacts may
remain for diagnosis. Choose a new directory for a retry. Convergence failures,
nonfinite vectors, and incomplete class assignments are rejected.

The offloading adaptation forwards dispatch options to LLM2Vec's two PEFT adapter
loads only during model construction; it does not change installed package files.
LLM2Vec's private tokenization methods are tied to the pinned dependency versions.

## Tests

The CPU suite uses fake inference, mocked adapter downloads, real scikit-learn
clustering, temporary Java sources, and the existing metrics CLI. It does not
download a model. Tests needing optional scientific packages skip if those
packages are absent; the full command below supplies them:

```bash
uv run --python 3.11 --with pytest==8.3.5 --with javalang==0.13.0 \
  --with numpy==1.26.4 --with scipy==1.14.1 --with scikit-learn==1.5.2 \
  --with pandas==2.2.3 --with pyarrow==17.0.0 pytest tests/test_monoembed.py -q
```

## Attribution

Adapted from the MonoEmbed replication package by Khouloud Sellami and Mohamed
Adel Saied and the existing local Pharmacy notebook. Upstream source is licensed
under GNU GPL version 3; the adapted runner is distributed under the same license
with the full text in [LICENSE](LICENSE). Model weights and the base model retain
their respective upstream terms. No model weights, training data, notebooks, or
legacy metric implementations are included here.
