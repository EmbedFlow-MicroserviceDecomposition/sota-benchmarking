# Cohesion at Message Level (CHM)

Measures the message-level cohesion of published inter-service operations.

## Formulation

$$f_{\text{msg}}(a, b) = \frac{\text{Jaccard}(\text{returns}_a, \text{returns}_b) + \text{Jaccard}(\text{params}_a, \text{params}_b)}{2}$$

Calculated as the mean pairwise message similarity across published inter-service operations per microservice.

## Execution

```bash
uv run metric.py --dataset-path <path_to_dataset> --output-path <path_to_tool_output>
```
