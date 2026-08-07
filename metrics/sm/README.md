# Structural Modularity (SM)

Evaluates the structural quality of microservice partitions based on Jin et al. (TSE 2021).

## Formulation

$$SM = \frac{1}{K} \sum_{k=1}^{K} \frac{\mu_k}{N_k^2} - \frac{1}{\binom{K}{2}} \sum_{i < j} \frac{\sigma_{ij}}{2 N_i N_j}$$

Where:
- $\mu_k$: number of intra-cluster edges in microservice $k$
- $\sigma_{ij}$: number of inter-cluster edges between microservices $i$ and $j$
- $N_k$: number of entities in microservice $k$
- $K$: number of microservices

## Execution

```bash
uv run metric.py --dataset-path <path_to_dataset> --output-path <path_to_tool_output>
```
