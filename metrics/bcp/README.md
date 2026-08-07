# Business Context Purity (BCP)

Measures the business domain entropy of classes within each microservice based on execution trace use-case labels.

## Formulation

$$BCP = \frac{1}{K} \sum_{k=1}^{K} \ln(m_k)$$

Where $m_k$ is the number of distinct business use-case labels associated with the classes in microservice $k$.

Lower values indicate higher business context purity per microservice.

## Execution

```bash
uv run metric.py --dataset-path <path_to_dataset> --output-path <path_to_tool_output>
```
