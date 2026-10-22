# CoGCN

Graph-convolutional autoencoder with outlier dilution and a k-means clustering loss over class structure and content:
Desai, Bandyopadhyay, Tamilselvam, *Graph Neural Network to Dilute Outliers for Refactoring Monolith Application*, AAAI 2021
([utkd/cogcn](https://github.com/utkd/cogcn), submodule `cogcn/`, pinned to `365a4cb`). Same IBM lineage as CHGNN.

> fyp-benchmarking only cloned CoGCN and never produced a cell, so everything here (adapter, runner, results) is new.

## Run

```bash
cd tools/cogcn
uv run tool.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore [--k 6] [--runner local]
uv run ../../metrics/compute_all.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore
```

`train.py` is unseeded (its `--seed` option is never used), so repeat runs with `scripts/run_sweep.py`. Default `--k` is
`train.py`'s stock 6. The Docker image `sota-cogcn` (`linux/amd64`, torch 1.8 CPU, networkx 2.5; built on first use) runs the
unmodified upstream `train.py` through `run_cogcn.py`; `--runner local` uses the current python instead (needs the old deps).

## Inputs built from `dataset.json` (`cogcn_adapter.py`)

CoGCN reads `struct.csv` and `content.csv` (headerless), one row per class:

- **struct**: symmetric 0/1 adjacency over classes from every edge type (CALL, FIELD, EXTENDS, IMPLEMENTS), no self loops.
- **content**: term frequencies, row-normalised, over a vocabulary of camelCase terms from the class's own name, its method names
  and the type names in its method signatures (JDK/primitive noise words removed, the same filter as CHD). This is a documented
  reconstruction: the published apps' content matrices ship pre-vectorised with no description of how they were derived.

Output: `output.json` (class FQNs from the k-means membership `train.py` pickles), `membership.json`, `classes.txt`
(row order), `run_info.json`, `train.log`. Datasets with no Java classes (genapp) get the error-form `output.json`.
