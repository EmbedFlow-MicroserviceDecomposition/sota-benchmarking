# VAE-C

Variational autoencoder (reconstruction + KL + "architecture" loss, reparameterisation `Sampling` layer, 2-D latent) whose
embeddings are clustered with fuzzy c-means (`skfuzzy.cluster.cmeans`, m=2, `error=0.005`, `maxiter=1000`) and hardened by
argmax over the membership matrix. Ported from `machine-learning/code.ipynb` of
[rokinmaharjan/benchmarking-monolith-to-microservices](https://github.com/rokinmaharjan/benchmarking-monolith-to-microservices)
(Maharjan, Baylor M.S. thesis). The upstream checkout is the submodule at `../ae-k/benchmarking-monolith-to-microservices`
(shared with AE-K); the algorithm lives in `../_common/vaec_core.py`, sharing graph/feature construction with AE-K.

## Run

```bash
cd tools/vae-c
uv run tool.py --dataset-path ../../datasets/bear-board --output-path outputs/bear-board [--seed 0] [--k 5]
uv run ../../metrics/compute_all.py --dataset-path ../../datasets/bear-board --output-path outputs/bear-board
```

## Cluster count

The thesis (Table 2.1) fixes **k = 5** on its own three apps, so `bear-board`, `pharmacy` and `autocare` default to `--k 5`.
Every other dataset uses the SSE elbow over k = 2..20 (same heuristic as AE-K). The thesis averages five attempts "since VAE's
latent space is based on the normal distribution": use `scripts/run_sweep.py --runs 5` on those three, `--runs 3` elsewhere.

Output: `output.json` (class FQNs) and `run_info.json` (`seed`, `k`, `capped`). Same path-cap deviation and N/A rule as AE-K
(see `../ae-k/README.md`).
