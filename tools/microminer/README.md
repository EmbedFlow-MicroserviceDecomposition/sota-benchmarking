# MicroMiner

Canonical 3-phase microservice identification approach reconstructed from the authors' replication notebooks in [`originals/`](originals/) (`createEmbad.ipynb`, `classificationML-Compiere.ipynb`, `microMiner.ipynb`):

> Trabelsi, I., Abdellatif, M., Abubaker, A., Moha, N., Mosser, S., Ebrahimi-Kahou, S., & Guéhéneuc, Y.-G. (2023). *From Legacy to Microservices: a Type-based Approach for Microservice Identification using ML and Semantic Analysis.* Journal of Software: Evolution and Process (JSEP).

## Pipeline Overview

1. **Phase 1 — Class Typing (`createEmbad.ipynb` + `classificationML-Compiere.ipynb`)**:
   - Resolves `.java` source files from `dataset.json` (`source_path` and `methods[*].file_path`).
   - Embeds each class using `microsoft/codebert-base` (`--embedder codebert`, 510-token chunks with `[CLS]`/`[SEP]`, mean-pooled `[CLS]` vectors) or an offline TF-IDF fallback (`--embedder tfidf`).
   - Derives layer seed labels (`application`, `entity`, `utility`) using the authors' exact JavaFX-POS seed lists (`microMiner.ipynb:98-100`) when matched and dot-separated package segments + architectural role tokens elsewhere (protecting `websphere` / `weblogger` from substring `"web"` collisions and checking leaf subpackages before root prefixes like `com.upachar.web`).
   - Splits `train_test_split(test_size=0.7, random_state=seed)` (ensuring `"utility"` and at least 2 classes are in `y_train`), fits `SVC(kernel="linear", C=2)`, and classifies the remaining 70%.
2. **Phase 2 — Typed-Service Identification (`microMiner.ipynb` cells 17–22)**:
   - Aggregates Table 1 static weights (`EXTENDS=100`, `IMPLEMENTS=100`, `FIELD=100`, `ASSOCIATION=25`, `INSTANTIATION=25`, `CALL=5`, scaled by `edge["weight"]`).
   - Builds undirected weighted graphs per layer (`application`, `entity`, `utility`) and runs `nx.community.louvain_communities(..., weight="weight", resolution=0.5, seed=seed)`.
   - Runs `fineTuneCluster` on `entity` and `application` services only (not `utility`, matching `microMiner.ipynb:510-512`) to merge singletons with a unique positive maximum connection weight.
3. **Phase 3 — Services to Microservices Mapping (`microMiner.ipynb` cells 7–13 & 23–31)**:
   - Tokenizes `.java` source (or FQN + method metadata if absent), removes the authors' `stopW` (`microMiner.ipynb:181`), splits camelCase (`re.findall(r".[^A-Z]*", ...)`), and lemmatizes (`WordNetLemmatizer` when available, else deterministic suffix fallback).
   - Computes class embeddings and word-count-weighted typed-service embeddings using either pretrained `word2vec-google-news-300` (`--word2vec google-news`, via `gensim.downloader`) or fast 300-D corpus-derived embeddings (`--word2vec corpus`).
   - Computes all-pairs shortest static paths via Floyd-Warshall (`INF = 999.0`, `100.0 / dis`) plus `2.0 * cosine_distance`, and assigns services using Fuzzy C-Means (`m = 3`, `coef = 1.0`) centered on `Application` services (`K = len(indexApplication)` by default, or `--k` override).

## CLI Usage

`tool.py` includes inline PEP 723 dependencies (`numpy`, `scipy`, `scikit-learn`, `networkx`, `torch`, `transformers`, `gensim`, `nltk`), while keeping heavy ML imports lazy so `tests/conftest.py:load_tool("microminer")` only needs the lightweight scientific stack.

```bash
cd tools/microminer
uv run tool.py \
  --dataset-path ../../datasets/jpetstore \
  --output-path outputs/jpetstore \
  --seed 42 \
  [--k 4] \
  [--embedder codebert|tfidf] \
  [--word2vec google-news|corpus] \
  [--soft-threshold 0.09]
```

### Options & Fallback Behaviour

- `--embedder`: Defaults to `codebert`. If omitted and `torch`/`transformers` or `.java` sources on disk are unavailable, falls back to `tfidf` and records `embedder_fallback_reason` in `run_info.json`. Explicitly passing `--embedder codebert` fails loudly (`exit 1`) if sources or `torch`/`transformers` are missing.
- `--word2vec`: Defaults to `google-news`. If omitted and `gensim` or the 1.6 GB model is unavailable, falls back to `corpus` and records `word2vec_fallback_reason`. Pass `--word2vec corpus` for fast offline sweeps.
- `--k`: Optional cluster-count override; default `None` uses MicroMiner's automatic `K = len(indexApplication)`.
- `--soft-threshold`: Threshold (default `0.09`, matching `val * 100 > 9` in `microMiner.ipynb:771`) recorded under `above_threshold_009` in `run_info.json`, while `output.json` stays a conflict-free hard partition (`argmax` membership).

### Outputs & N/A Contract

- `output.json`: `{"tool": "MicroMiner", "microservices": {"microservice_1": [...]}}` (class FQNs).
- `run_info.json`: `seed`, `k`, `auto_k`, `embedder`, `word2vec`, `phase1` counts, `phase2_services`, and `above_threshold_009`.
- Datasets without Java classes (e.g., `genapp`) write `{"error": "... cell is N/A", "tool": "MicroMiner"}` and exit `1`. Missing `dataset.json` writes an error without `"N/A"` and exits `1`.

## Notebook Deviations & Fixes

- **All services kept in `nodeList`**: Isolated services with zero inter-service edges are retained in `nodeList` (whereas `microMiner.ipynb:639` built `nodeList` from `GServices.nodes` only) so every class receives an assignment (100% coverage).
- **Removed hardcoded `resultedMS.pop(10)`** (`microMiner.ipynb:776`).
- **Fixed `train_test_split` index alignment**: Moving a `"utility"` sample into `train_idx` preserves 1-to-1 class coverage without dropping the tail test element (`classificationML-Compiere.ipynb:74-79`).

## `sita-gpu` Evaluation (`microsoft/codebert-base`, `seed=42`, automatic `K`)

Evaluated on `sita-gpu` (PyPI `torch` ran on CPU because the host NVIDIA driver 450.102.04 supports CUDA 11.0) against `jpetstore` (24 classes, 61 edges) and `javafx-pos` (56 classes, 175 edges) extracted via `datasets/extractor`:

| Dataset | Word2Vec | K | Coverage | CHM ↑ | CHD ↑ | SM ↑ | ICP ↓ | IFN ↓ | NED ↑ | BCP ↓ |
| --- | --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `jpetstore` | `google-news` | 4 | 24/24 | 0.6741 | 0.5806 | 0.1267 | 0.2385 | 1.50 | 0.8333 | 1.4452 |
| `jpetstore` | `corpus` | 4 | 24/24 | 0.6741 | 0.5806 | 0.1267 | 0.2385 | 1.50 | 0.8333 | 1.4452 |
| `javafx-pos` | `google-news` | 12 | 56/56 | 0.7234 | 0.6441 | 0.1066 | 0.5155 | 1.25 | 0.8036 | 0.5874 |
| `javafx-pos` | `corpus` | 12 | 56/56 | 0.6817 | 0.6043 | 0.0960 | 0.5311 | 1.25 | 0.7857 | 0.5874 |

*(Metrics measured immediately before switching the `nltk_data` lookup path to `~/nltk_data`; in both runs NLTK declined to write to a group-writable directory so tokenization used the deterministic suffix lemmatizer, and a post-edit smoke run on `sita-gpu` confirmed identical `K=4` and `K=12` partitions.)*

## Tests

```bash
uv run --python 3.12 --with pytest --with numpy==2.4.4 --with scipy==1.18.0 --with scikit-learn==1.9.0 --with networkx pytest tests/test_microminer_tool.py -v
```
