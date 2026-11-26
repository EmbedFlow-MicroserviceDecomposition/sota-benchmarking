# HierDec / HyDec

Hierarchical DBSCAN-based microservice decomposition using structural, semantic, and optional dynamic call views:
- **HierDec**: Sellami, Saied, Ouni, *A Hierarchical DBSCAN Method for Extracting Microservices from Monolithic Applications*, EASE / SANER 2022
- **HyDec**: Sellami, Saied, Ouni, Abdalkareem, *Combining Static and Dynamic Analysis to Decompose Monolithic Application into Microservices*, ICSOC 2022
- Upstream: [khaledsellami/decomp-hydec](https://github.com/khaledsellami/decomp-hydec), submodule `decomp-hydec/` pinned to `bc56be4`.

> Note on provenance: `Eshin22/HDBScan_evaluation` cloned `decomp-hydec` into its tree but never actually invoked it; its `evaluate_metrics.py` instead ran custom SciPy hierarchical agglomerative clustering (`scipy.cluster.hierarchy.linkage` / `fcluster`) and mislabelled the results as HDBSCAN. This adapter wraps unmodified upstream `khaledsellami/decomp-hydec` directly.

## Run

```bash
cd tools/hydec
uv run tool.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore
uv run ../../metrics/compute_all.py --dataset-path ../../datasets/jpetstore --output-path outputs/jpetstore
```

Default mode is `--approach hierDec` (structural + semantic iterative DBSCAN with `epsilon=0.65`, `min_samples=2`, `strategy=alternating_epsilon`), which applies to all 12 Java datasets (`genapp` is COBOL and writes an N/A `output.json`).

Pass `--approach hyDec` to also include the dynamic analysis pass from `datasets/<dataset>/fosci_trace.csv.gz`:

```bash
uv run tool.py --dataset-path ../../datasets/spring-petclinic --output-path outputs/spring-petclinic-hydec --approach hyDec
```

## Inputs built from `dataset.json` (`hydec_adapter.py`)

In a temporary working directory under `--output-path`, `hydec_adapter.py` constructs the file layout expected by `decomp-hydec`:

- **`structural/class_calls.npy` & `structural/class_names.json`**: $N \times N$ directed dependency weight matrix over sorted class FQNs, summing weights across all edges (`CALL`, `FIELD`, `EXTENDS`, `IMPLEMENTS`) in `dataset.json["edges"]` (no self-loops).
- **`semantic/class_tfidf.npy` & `semantic/class_names.json`**: $N \times M$ TF-IDF matrix over camelCase/snake_case domain tokens (Java keywords and English stop words removed). Source files are read via `dataset.json["source_path"]` and `methods[*].file_path` (plus source-root matching for method-less classes); when `.java` files are unavailable on disk, tokens fall back to camelCase terms from class names and method signatures in `dataset.json`.
- **`dynamic/class_calls.npy` & `dynamic/class_names.json`** (`--approach hyDec` only): $M \times M$ directed runtime call-count matrix built from `datasets/<dataset>/fosci_trace.csv.gz`, filtered to classes present in `dataset.json`. Missing traces write a retriable error `output.json` (without `"N/A"`).

## Compatibility, Layer Selection, and Outliers

- **Runtime shims**: Unmodified `decomp-hydec` passes `OneHotEncoder(sparse=False)` (removed in `scikit-learn>=1.4`) and imports `grpc` / protoc-3 protobuf definitions at package load time even when reading local `.npy` matrices. Before importing `hydec`, `tool.py` applies a `OneHotEncoder.__init__` wrapper (`sparse` -> `sparse_output`) and stubs unused gRPC client classes when `grpcio`/`protobuf` are absent, allowing execution on Python 3.12 + `scikit-learn==1.9.0` without Docker.
- **Layer selection**: `decomp-hydec` returns a hierarchy of clustering `layers`. If `layers[-1]` collapses all classes into a single cluster (`len(set(layers[-1])) == 1`) while an earlier layer has `>= 2` clusters, `tool.py` selects the last layer with `>= 2` clusters; `selected_layer`, `total_layers`, and `collapsed_fallback` are recorded in `run_info.json`.
- **Outliers (`-1`)**: With default `include_outliers=False`, `AbstractAnalysis.generate_clusters` promotes DBSCAN `-1` noise points to unique cluster IDs internally. If any `-1` label remains in the selected layer, `tool.py` assigns each outlier to its own singleton `microservice_N` so 100% of dataset classes are covered (`outliers` and `outlier_policy: "singleton"` recorded in `run_info.json`).
- **Outputs**: `output.json` (class FQNs), `layers.json` (raw layer history), and `run_info.json`.
