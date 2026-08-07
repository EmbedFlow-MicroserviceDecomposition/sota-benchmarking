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
