# AE-K (baseline)

Plain autoencoder (reconstruction + "architecture" loss pulling `Z.Zᵀ` towards the adjacency matrix, no KL term) with a 2-D
embedding, clustered with hard KMeans. This is the **AE-K baseline** of Rokin Maharjan's Baylor M.S. thesis
(*Microservice Decomposition and Message Queues*), ported from `machine-learning/ae.ipynb` of
[rokinmaharjan/benchmarking-monolith-to-microservices](https://github.com/rokinmaharjan/benchmarking-monolith-to-microservices)
(submodule `benchmarking-monolith-to-microservices/`, pinned to `81031a6`, shared with `../vae-c`). The algorithm lives in
`../_common/vaec_core.py`; `tool.py` only wires `dataset.json` to it.

> fyp-benchmarking first mislabelled this method "VAE-C"; the real VAE-C is `../vae-c`.

## Run

```bash
cd tools/ae-k
uv run tool.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore [--seed 0]
uv run ../../metrics/compute_all.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore
```

`uv` installs the pinned deps from the script header (Python 3.11/3.12, TensorFlow 2.21, Keras 3). No Docker needed.

## Pipeline

1. `dataset.json` → class adjacency (every edge type, deduplicated, no self edges) and `datasets/<dataset>/entrypoints.txt`.
2. Entrypoint-reachability matrix `E` and co-entrypoint-path matrix `C` (DFS from each entrypoint), feature matrix
   `X = D^-1/2 · A · D^-1/2 · [E | C]`, standardised.
3. Autoencoder, 8000 full-batch epochs, Adam(lr=0.001).
4. KMeans swept over k = 2..20 (`n_init=10`, `random_state=0`); k chosen by the SSE elbow (the notebook has no fixed default k).

Output: `output.json` (class FQNs), `run_info.json` (`seed`, chosen `k`, `capped`). The training is unseeded unless `--seed` is
given (the seed used is always recorded); repeat runs with `scripts/run_sweep.py`.

## Notes and deviations

- The all-simple-paths DFS is exponential on branching/cyclic graphs; exploration is capped at `--max-paths` (default 20000) per
  entrypoint with a `WARNING`. It triggered for JForum and Roller in fyp-benchmarking and `run_info.json` records it.
- Datasets without `datasets/<dataset>/entrypoints.txt` (genapp, javafx-pos) get the error-form `output.json`.
