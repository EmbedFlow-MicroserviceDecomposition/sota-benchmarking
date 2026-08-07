# Interface Number (IFN)

Measures the average number of exposed entry points/interfaces per microservice.

## Formulation

$$IFN = \frac{1}{K} \sum_{k=1}^{K} | \text{ExposedInterfaces}_k |$$

Where $\text{ExposedInterfaces}_k$ is the set of distinct methods in microservice $k$ invoked from outside microservice $k$.

## Execution

```bash
uv run metric.py --dataset-path <path_to_dataset> --output-path <path_to_tool_output>
```
