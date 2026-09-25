# Triplet-Guided CHGNN

This directory integrates the **Triplet-Guided CHGNN** toolchain developed by Mono2Distributed.

- **Repository**: [https://github.com/Mono2Distributed/triplet-guided-chgnn](https://github.com/Mono2Distributed/triplet-guided-chgnn)
- **Submodule Location**: `tools/triplet-guided-chgnn/triplet-guided-chgnn`

---

## Architecture & Methodology

Triplet-Guided CHGNN formulates monolithic application decomposition as heterogeneous graph representation learning:
1. **Heterogeneous Graph Construction**: Applications are modeled as heterogeneous graphs containing program nodes (classes/methods) and resource nodes (database tables/HTTP endpoints), connected by `CALL` and `CRUD` relations.
2. **Weak Supervision via Triplet Loss**: Employs weakly supervised triplet contrastive learning. Anchor and positive nodes are sampled from inferred service groups (extracted by the parser, optionally assisted by a local LLM via Ollama), while negative nodes are sampled across different groups.
3. **Composite Embeddings & Clustering**: Optimizes node/edge autoencoding and triplet loss in a joint latent space, followed by clustering into candidate microservices (outputting CMA JSON format).

---

## Tool Usage (`tool.py`)

In accordance with benchmark principles, dataset mapping dictionaries have been completely removed. Running the tool always requires providing the dataset path via `--dataset-path`:

```bash
# Run decomposition on a benchmark dataset (uses cached graphs if available)
python3 tools/triplet-guided-chgnn/tool.py --dataset-path datasets/acme-air

# Run from scratch ignoring pre-computed graphs (forces full parser + Ollama pipeline)
python3 tools/triplet-guided-chgnn/tool.py --dataset-path datasets/acme-air --force-recompute

# Run on an arbitrary new dataset (e.g. bear-board)
python3 tools/triplet-guided-chgnn/tool.py --dataset-path datasets/bear-board

# Run inside the container environment
python3 tools/triplet-guided-chgnn/tool.py --dataset-path datasets/acme-air --docker-image triplet-chgnn:latest

# Parse existing CMA format results without re-training
python3 tools/triplet-guided-chgnn/tool.py --dataset-path datasets/acme-air --parse-only
```

---

## Dataset Ingestion Workflow

The tool handles any dataset dynamically without manual configuration:

1. **Path Resolution**: The tool extracts `dataset_name` directly from `--dataset-path` and inspects `dataset.json` (resolving `source_path`) to find the application source code.
2. **Pre-computed Cache Detection**: If pre-computed graph files exist under `data_layer/utilities/data/<dataset_name>_<model>`, they are ingested directly.
3. **Dynamic Graph Construction**: If graph files are not present (such as when running a new dataset like `datasets/bear-board`), the adapter automatically runs the parser pipeline:
   - `parser/main.py`: Discovers compiled classes and methods, annotates semantic vertices (using local Ollama if available, or heuristic fallback), and converts graph matrices via `EnhancedM2DToChgnnConverter`.
   - `parser/generate_servlet_services.py`: Derives service clusters and contrastive triplets.
   - The resulting AST, call graphs, feature matrices (`content.csv`, `struct.csv`), and configurations are assembled into `data_layer/utilities/data/<dataset_name>_<model>`.
4. **Model Training & Output**: The CHGNN model trains with triplet contrastive loss and writes the final cluster partition to `outputs/<dataset_name>/output.json`.

---

## Environment & Requirements

- **Python**: 3.8
- **PyTorch**: 1.8.0
- **PyTorch Geometric (PyG)**: 2.0.1 (`torch-scatter 2.0.8`, `torch-sparse 0.6.12`, `torch-cluster 1.5.9`)
- **Dependencies**: `scikit-learn`, `networkx`, `pandas`, `numpy`, `scipy`
- **Optional (for semantic LLM summarization)**: Ollama running model `gemma3:1b` (accessed via local REST API at `http://localhost:11434`). If Ollama is not present, the parser automatically uses rule-based semantic fallbacks without interruption.

A ready-to-build [Dockerfile](file:///home/yumeth/Projects/fyp-sota/tools/triplet-guided-chgnn/Dockerfile) is provided to run the toolchain inside an isolated container environment.
