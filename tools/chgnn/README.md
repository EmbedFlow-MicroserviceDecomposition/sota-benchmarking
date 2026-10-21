# CHGNN (original)

**C**ommunity-**H**ypergraph **GNN** for monolith decomposition: Mathai et al., *Monolith to Microservices:
Representing Application Software through Heterogeneous Graph Neural Network*, IJCAI 2022.
Upstream: [Alex-Mathai-98/Monolith-to-Microservices](https://github.com/Alex-Mathai-98/Monolith-to-Microservices)
(submodule `Monolith-to-Microservices/`, pinned to `f94803e`). Not to be confused with `../triplet-guided-chgnn`.

## Pipeline

```bash
cd tools/chgnn
uv run tool.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore
uv run ../../metrics/compute_all.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore
```

1. `chgnn_adapter.py` turns `dataset.json` (class edges: CALL/FIELD weights, EXTENDS, IMPLEMENTS) plus
   `configs/<dataset>/` into CHGNN's input folder (`inter_class_usage.json`, a synthesised `callgraph.dot` with
   entrypoint annotations, `service.json`, `db.json`, `seeds.txt`, `ignore_classes.txt`, `gcnconfig_with_edge_loss.json`).
2. `run_chgnn.py` runs the **unmodified** upstream `Graph.py` once (it hard-codes 30 runs; the launcher patches that to 1
   in memory) inside the `sota-chgnn` Docker image (built on first use; `--runner local` uses the current python instead).
3. `clusters_with_edge_loss.json` (`{cluster: [classes, "<x>-res" resources]}`) becomes `output.json`
   (class FQNs, resource nodes dropped).

The submodule is copied to a temp dir per run, so it stays clean. CHGNN is unseeded; repeat runs with `scripts/run_sweep.py`.

## Per-dataset config (`configs/<dataset>/`)

CHGNN needs what its authors hand-curated per app: `entrypoints.txt` (web entrypoint classes), `dbmap.json`
(`{class: {table: "CRUD"}}`), `seeds.txt` (one line per cluster seed: classes plus `<table>-res` resources) and an optional
`ignore_classes.txt`. They were carried over from fyp-benchmarking. The adapter fails loudly if a config names a class that is
not in `dataset.json`. Classes with no edges are excluded automatically (a zero usage row NaNs the GCN) and stale ignore
entries are dropped with a note.

| Dataset | Config |
| :--- | :--- |
| acme-air, apache-roller, autocare, bear-board, jforum, jpetstore, pharmacy, spring-blog | carried over from fyp-benchmarking |
| spring-petclinic | rewritten for the pinned 1.5.x checkout (`visit.Visit`, no `PetTypeRepository`; fyp-benchmarking used a newer commit) |
| daytrader, plants | `BUNDLED`: the authors' own prepared inputs shipped in the CHGNN repo (`dayTrader`, `pbw`), as in fyp-benchmarking; there are no seeds/DB map for our checkouts |
| genapp, javafx-pos | no config: `output.json` is the error form (COBOL app / desktop app without web entrypoints) |

## Notes

- `acme-air` here is the morphia/wxs AcmeAir (`f161227`, 84 classes); CHGNN's paper analysed a 38-class mongo variant, so do not
  compare it with the paper's acme row.
- Docker image is `linux/amd64` (`torch_scatter` has no arm64 CPU wheels); it is emulated on Apple silicon and slower.
