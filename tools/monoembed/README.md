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

From a fresh clone on the GPU server:

```bash
git clone --branch migrate/monoembed \
  https://github.com/EmbedFlow-MicroserviceDecomposition/sota-benchmarking.git
cd sota-benchmarking

git -c 'url.https://github.com/.insteadOf=git@github.com:' \
  submodule update --init datasets/pharmacy/pharmacy
```

Dataset adapters retain their ordinary interfaces. All MonoEmbed preparation lives
in `tools/monoembed/prepare.py`, with no tool-specific module, flag, or imports in
`datasets/`. Prepare a private input snapshot from the common dataset:

```bash
uv run tools/monoembed/prepare.py \
  --dataset-path datasets/pharmacy \
  --output-path tools/monoembed/.cache/datasets/pharmacy
```

If common `dataset.json` is missing, preparation invokes its normal `dataset.py`
first. Existing common metadata is left unchanged. The tool then builds its
bundled Spoon extractor as needed and writes the enriched `dataset.json` under
its ignored cache. This snapshot contains source text, method/edge information,
use-case mappings, and MonoEmbed provenance. Paths are resolved from the common
metadata. Preparation rejects output directories inside `datasets/`.

### Supported datasets and source scope

| Dataset | Source checkout / scope in MonoEmbed mode |
| --- | --- |
| acme-air | `acmeair/`: all production Maven Java roots |
| apache-roller | `roller/app/src/main/java` only |
| autocare | `autocare-nepal/src/main/java` |
| bear-board | `bear-board/src/main/java` |
| javafx-pos | `JavaFX-Point-of-Sales/src/main/java` |
| jforum | pinned `jakartaEE/`: Maven production roots, or Eclipse `src/` |
| pharmacy | `pharmacy/src/main/java` |
| spring-blog | `SpringBlog/src/main/java` |
| spring-petclinic | `spring-petclinic/src/main/java` |
| daytrader, jpetstore, plants | all production Java roots of their existing submodules |

The first nine cover the Java datasets prepared in the old MonoEmbed workspace. The
workflow uses this benchmark's current submodule pins; it never checks out the
historical notebook revisions over them. JForum, Roller, and PetClinic pins differ
from the old bundles, so historical class counts and scores are not assumed.
Java type names consistently use dots for named nested types and exclude anonymous
and method-local types; consequently Acme Air uses named types rather than the old
86-type protocol that also included two anonymous classes. This choice is recorded
in each dataset's provenance. CICS Genapp is COBOL and has no MonoEmbed adapter.

Java source discovery handles multi-module Maven projects and Eclipse `src/`
layouts. The same roots feed both source-text extraction and benchmark method/edge
extraction. Valid syntax unsupported by `javalang` uses Spoon's declared-method
metadata; affected files are listed in `spoon_method_fallback_files`. Graphs remain
static approximations, and overloads still share the repository's method ID format.

To initialize just these nine source repositories from the benchmark root:

```bash
git -c 'url.https://github.com/.insteadOf=git@github.com:' submodule update --init \
  datasets/acme-air/acmeair datasets/apache-roller/roller \
  datasets/autocare/autocare-nepal datasets/bear-board/bear-board \
  datasets/javafx-pos/JavaFX-Point-of-Sales \
  datasets/jforum/jakartaEE datasets/pharmacy/pharmacy \
  datasets/spring-blog/SpringBlog datasets/spring-petclinic/spring-petclinic
```

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

From the repository root, after preparing the tool-owned Pharmacy snapshot:

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
  --dataset-path tools/monoembed/.cache/datasets/pharmacy \
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
  --dataset-path tools/monoembed/.cache/datasets/pharmacy \
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

### Run the original dataset cohort sequentially on the server

Set the token, writable cache variables, and `CUDA_VISIBLE_DEVICES` as above. Run
inside tmux from the benchmark root. Choose an unused run ID; the successful
Pharmacy run does not need to be repeated unless you want a fresh result.

```bash
run_id=generalized_01
for dataset_name in acme-air apache-roller autocare bear-board \
                    javafx-pos jforum pharmacy spring-blog spring-petclinic; do
  uv run tools/monoembed/prepare.py \
    --dataset-path "datasets/$dataset_name" \
    --output-path "tools/monoembed/.cache/datasets/$dataset_name" || break
  uv run tools/monoembed/tool.py \
    --dataset-path "tools/monoembed/.cache/datasets/$dataset_name" \
    --output-path "tools/monoembed/outputs/$dataset_name/$run_id" || break
  uv run metrics/compute_all.py \
    --dataset-path "tools/monoembed/.cache/datasets/$dataset_name" \
    --output-path "tools/monoembed/outputs/$dataset_name/$run_id" || break
done
```

Use the same prepared snapshot for the model and metrics so both consume the
same class universe and graph. Preparation downloads parser/build dependencies only. Model files are loaded on
the GPU server and reused from the existing caches across datasets. Check all
seven metric files for every completed run; the metrics runner's caught-error
behavior described above also applies to this loop.

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
  --with pandas==2.2.3 --with pyarrow==17.0.0 \
  pytest tests/test_monoembed.py -q
```

## Attribution

Adapted from the MonoEmbed replication package by Khouloud Sellami and Mohamed
Adel Saied and the existing local Pharmacy notebook. Upstream source is licensed
under GNU GPL version 3; the adapted runner is distributed under the same license
with the full text in [LICENSE](LICENSE). Model weights and the base model retain
their respective upstream terms. No model weights, training data, notebooks, or
legacy metric implementations are included here.
