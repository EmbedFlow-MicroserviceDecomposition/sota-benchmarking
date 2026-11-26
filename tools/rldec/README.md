# RLDec

Deep Q-Network (DQN) reinforcement learning decomposition over structural and semantic class-level modularity rewards:
Sellami & Saied, *Extracting microservices from monolithic systems using deep reinforcement learning*, Empirical Software Engineering (EMSE) 2025
([khaledsellami/decomp-rldec](https://github.com/khaledsellami/decomp-rldec), submodule `decomp-rldec/`, pinned to `4518754`).

> Note: `Eshin22/RLDec` forked `decomp-rldec` and added regex extraction plus Agglomerative/Spectral clustering sweeps, without ever training or running RLDec DQN itself (no checkpoints or RLDec partitions exist in that fork). This adapter wraps the unmodified canonical `khaledsellami/decomp-rldec` package (`rldec.train_model.train_model` and `rldec.decompose.generate_decomposition`).

## Run

```bash
cd tools/rldec
uv run tool.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore [--iterations 20] [--runner uv|docker|local]
uv run ../../metrics/compute_all.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore
```

Options:
- `--approach`: `combsequential` (default, combined structural + semantic modularity), `sequential`, or `flattened`.
- `--feature`: `structural` (default) or `semantic` (used by `sequential`/`flattened`; ignored by `combsequential`).
- `--iterations`: Ray RLlib DQN training iterations (default `20`).
- `--episodes` / `--strategy`: rollout count (default `1`) and selection (`last` default, or `best`).
- `--runner`:
  - `uv` (default): launches `run_rldec.py` under Python 3.10 using its PEP 723 script dependencies (`ray[rllib]==2.9.2`, `torch>=2.1.0,<2.6`, `gymnasium>=0.28.1`, `numpy>=1.26.4,<2.0`, `pandas<=2.2.0`, `pyarrow`, `scikit-learn>=1.2.2,<1.4.0`, `scipy`, `networkx`, `protobuf>=4.25.2`, `grpcio`, `dm-tree`, `lz4`, `setuptools<70` for `ray.data`'s `pkg_resources._vendor` import). `tool.py` and `rldec_adapter.py` never import `ray` or `torch` at top level so lightweight pytest environments can import `tool.py`.
  - `docker`: builds and runs image `sota-rldec` (`tools/rldec/Dockerfile`, `linux/amd64`, Python 3.10) with `--user uid:gid` and a Snap-safe temporary work directory inside `--output-path`.
  - `local`: runs `run_rldec.py` in the current Python interpreter.

`run_rldec.py` probes `torch.cuda.is_available()` and overrides `num_gpus` (`1` on CUDA GPU, `0` on CPU), clamps `max_microservices` to `min(20, max(2, N))`, and passes `eval_model=False` (avoiding upstream's hardcoded `./data/REPLACE_WITH_APP_NAME/...` `word_count_path` bug).

## Inputs built from `dataset.json` (`rldec_adapter.py`)

`rldec_adapter.py` writes the `.parquet` directory `<work>/data/<app>/` expected by `rldec.data_handler.DataHandler` (bypassing the external gRPC parsing service):

- **`class_interactions.parquet`**: $N \times N$ DataFrame (`index=classes`, `columns=classes`) summing structural edge weights (`CALL`, `FIELD`, `EXTENDS`, `IMPLEMENTS`) from `dataset.json["edges"]` (no self loops).
- **`class_word_count.parquet`**: $N \times N$ DataFrame (`index=classes`, `columns=classes`) shared-vocabulary matrix computed via Khaled Sellami's formula (`rldec/callbacks.py:76-78`):
  1. Extract the $N \times M$ Bag-of-Words matrix `W` from `.java` files under `source_path` / `methods[*].file_path` (stripping comments and splitting camelCase/snake_case identifiers, falling back to camelCase class/method signature tokens from `dataset.json` when `.java` sources are unavailable).
  2. Retain vocabulary columns whose document frequency is $\le \max(1, \lfloor N / 2 \rfloor)$ (falling back to unfiltered `W` if every term exceeds the threshold on tiny fixtures).
  3. Compute $S = W_{\text{filtered}} W_{\text{filtered}}^{\top}$ ($N \times N$). This matches upstream's `callbacks.py` semantic matrix and satisfies `rldec/features.py:47`'s `both_axes=True` square assertion without modifying the submodule.
- **`class_tfidf.parquet`**: $N \times M$ TF-IDF matrix (`index=classes`) used by `DataHandler.get_names()`.

## Outputs & N/A Contract

Writes `output.json` (`{"tool": "RLDec", "microservices": {"microservice_1": [...], ...}}`), `decomposition.json` (raw RLDec `partition_*` output), `run_info.json`, and `train.log`. Empty partitions and `-1` outlier partitions are omitted when building `microservices`. Datasets with 0 or `< 2` Java classes (such as `genapp`) write an error `output.json` mentioning `N/A` and exit `1`.
