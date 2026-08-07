# Non-Extreme Distribution (NED)

Measures the fraction of microservices whose size falls within a non-extreme range.

## Formulation

Supports both:
1. **Fixed bounds:** Default range `[5, 20]` classes.
2. **Relative bounds:** Mean size $\pm \epsilon \cdot \text{mean}$ (default $\epsilon = 0.5$).

$$NED = \frac{|\{ k : \text{size}_k \in [\text{min\_size}, \text{max\_size}] \}|}{K}$$

## Execution

```bash
uv run metric.py --dataset-path <path_to_dataset> --output-path <path_to_tool_output>
```
