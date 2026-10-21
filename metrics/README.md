# Evaluation Metrics Engine

This directory contains the implementations of the quantitative evaluation metrics used to assess microservice decomposition quality.

## Overview of Metrics

| Metric | Full Name | Focus | Range / Goal |
| :--- | :--- | :--- | :--- |
| **CHM** | Cohesion at Message Level | Pairwise Jaccard similarity of method parameters and return types across published inter-service operations. | `[0.0, 1.0]` (Higher is better) |
| **CHD** | Cohesion at Domain Level | Pairwise Jaccard similarity of domain terms in operation signatures. | `[0.0, 1.0]` (Higher is better) |
| **SM** | Structural Modularity | Ratio of intra-cluster edges vs inter-cluster edges based on Jin et al. (TSE 2021). | `[-1.0, 1.0]` (Higher is better) |
| **ICP** | Inter-Call Percentage | Ratio of inter-service calls over total calls. | `[0.0, 1.0]` (Lower is better) |
| **IFN** | Interface Number | Average number of distinct exposed entry points per microservice. | `>= 0.0` (Lower is better) |
| **NED** | Non-Extreme Distribution | Proportion of microservices with reasonable size (e.g. `[5, 20]` classes or relative `eps=0.5`). | `[0.0, 1.0]` (Higher is better) |
| **BCP** | Business Context Purity | Mean entropy of business use-case labels across classes in each microservice. | `>= 0.0` (Lower is better) |

---

## Usage

### 1. Run All Metrics via Unified Runner

To evaluate all metrics for a given dataset and tool decomposition output:

```bash
uv run metrics/compute_all.py \
  --dataset-path datasets/acme-air \
  --output-path tools/mono2micro/outputs/acme-air
```

This updates/generates individual `<metric>_score.json` files and a consolidated `metrics_summary.json` inside the tool's output directory.

### 2. Run Individual Metric Evaluators

Each metric directory contains a standalone `metric.py`:

```bash
# Example: Evaluate SM
uv run metrics/sm/metric.py \
  --dataset-path datasets/acme-air \
  --output-path tools/mono2micro/outputs/acme-air
```

---

## Variants and extra fields

| Score file | Field | Meaning |
| :--- | :--- | :--- |
| `sm_score.json` | `score_undirected` | CHGNN released-repo SM: edges collapse to unordered pairs, intra pairs count twice. |
| `ifn_score.json` | `score_cross_edge` | CHGNN released-repo IFN: distinct undirected cross-partition node pairs per partition. |
| `ned_score.json` | `score_relative` | CHGNN relative-bounds NED (`eps=0.5`). |
| `ned_score.json` | `score_triplebound` | TripleBound NED (arXiv:2609.11212, Eq. 10 as read by fyp-benchmarking): classes in extreme partitions / #partitions, lower is better, unbounded. |
| every `*_score.json` | `coverage` | `classes`, `assigned`, `unassigned`, `unmatched_ids`, `conflicts` from `partition.py`. |

## Partition resolution (`partition.py`)

`output.json` may list class FQNs or method ids. Method ids roll up to their class by majority vote (ties go to the
smallest cluster id); classes explode to all their methods. Ids that match nothing in `dataset.json` are counted in
`coverage.unmatched_ids`, never fuzzy-matched (a bare simple name matches only if it is unique). A microservice with no matched
class is not counted as a cluster. An `output.json` that is an error record (`{"error": ...}`) is never scored.

BCP drops the `Unknown` use-case label; `fyp-benchmarking` had no such label because its use cases came from entrypoint reachability.
