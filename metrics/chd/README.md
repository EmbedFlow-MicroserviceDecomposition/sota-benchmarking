# Cohesion at Domain Level (CHD)

Measures the domain-level term cohesion of published inter-service operation signatures.

## Formulation

$$f_{\text{dom}}(a, b) = \text{Jaccard}(\text{DomainTerms}(a), \text{DomainTerms}(b))$$

Extracts domain words from method names, parameters, and return types (excluding language primitives and general keywords).

## Execution

```bash
uv run metric.py --dataset-path <path_to_dataset> --output-path <path_to_tool_output>
```
