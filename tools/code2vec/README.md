# Code2Vec

Canonical implementation of **Code2Vec** for microservice decomposition (Al-Debagy & Martinek, 2021,
*"A Microservice Decomposition Method Through Using Distributed Representation of Source Code"*) backed by
the official [`tech-srl/code2vec`](https://github.com/tech-srl/code2vec) submodule (`code2vec/`, pinned to
`77637c5`).

## Pipeline

```bash
cd tools/code2vec
uv run tool.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore
uv run ../../metrics/compute_all.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore
```

1. **AST path-context extraction (`code2vec_adapter.py`)**: Resolves `.java` files for every class in
   `dataset.json["classes"]` (via `methods[*].file_path` and `dataset.json["source_path"]`) and runs
   `code2vec/JavaExtractor/JPredict/target/JavaExtractor-0.0.1-SNAPSHOT.jar`
   (`--max_path_length 8 --max_path_width 2 --no_hash`), hashing paths with `java_string_hashcode` and keeping
   up to `MAX_CONTEXTS = 200` contexts per method.
2. **Pretrained neural embedding**: Downloads and caches
   `https://s3.amazonaws.com/code2vec/model/java14m_model.tar.gz` into `.cache/models/java14_model/`
   (override with `--model-path`), loads `dictionaries.bin` and the 4 inference tensors from
   `saved_model_iter8.release` via `tf.train.load_checkpoint`, and evaluates the attention-weighted context
   encoder (`tokens[src] + paths + tokens[dst] -> tanh(@ TRANSFORM) -> softmax(log(mask) + @ ATTENTION) -> sum`)
   to obtain 384-D method vectors.
3. **Class aggregation & methodless fallback**: Averages method vectors per class (`v_class = mean(v_method)`).
   For methodless classes (interfaces, enums, DTOs with 0 method bodies), subtokens from the class name and
   declared method names are embedded through `WORDS_VOCAB` and projected with `tanh([w, 0, w] @ TRANSFORM)`.
4. **Clustering (`tool.py`)**: Clusters class vectors automatically using `AffinityPropagation` (`--damping`,
   default `0.5`, `--seed`, default `42`). An explicit `--k <int>` runs `KMeans` instead; if Affinity
   Propagation fails to converge or collapses to a single cluster, a silhouette sweep over
   `k in [2, min(20, N - 1)]` selects the partition.

## CLI Options

- `--dataset-path`: Dataset directory containing `dataset.json` (required)
- `--output-path`: Output directory for `output.json` and raw artifacts (required)
- `--seed`: Random seed (default `42`)
- `--k`: Optional fixed cluster count override
- `--damping`: `AffinityPropagation` damping factor in `[0.5, 1.0)` (default `0.5`)
- `--model-path`: Optional path to a local checkpoint prefix or model directory (skips download)

## Prerequisites & Artifacts

- **Java**: JRE/JDK 11+ (`java` on `PATH`) for `JavaExtractor-0.0.1-SNAPSHOT.jar`.
- **Python**: Dependencies are declared inline in `tool.py` (`numpy==2.4.4`, `scikit-learn==1.9.0`,
  `tensorflow==2.21.0`). Submodule init required: `git submodule update --init tools/code2vec/code2vec`.
- **Outputs**: `output.json` (`{"tool": "Code2Vec", "microservices": ...}` with class FQNs), `run_info.json`,
  `partition.json`, `class_vectors.npy`, and `classes.txt`.
- **Applicability**: Datasets with zero Java classes (such as `genapp`) write an error `output.json` marked
  `cell is N/A` and exit `1`.

## Tests

```bash
uv run --python 3.12 --with pytest --with numpy==2.4.4 --with scikit-learn==1.9.0 \
  --with tensorflow==2.21.0 pytest tests/test_code2vec_tool.py -v
```
