# Inter-Call Percentage (ICP)

Measures the proportion of inter-service calls over total calls across microservices.

## Formulation

$$ICP = \frac{\sum \text{Inter-service Call Weights}}{\sum \text{Total Call Weights}}$$

Lower values indicate better isolation between microservices.

## Execution

```bash
uv run metric.py --dataset-path <path_to_dataset> --output-path <path_to_tool_output>
```
