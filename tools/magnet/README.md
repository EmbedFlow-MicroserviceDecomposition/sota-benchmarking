# MAGNET Tool Adapter

This directory contains the wrapper and orchestrator for the **MAGNET** microservice decomposition tool.
The core tool is tracked as a Git submodule in the `MAGNET/` directory.

## Structure
- `MAGNET/`: Git submodule containing the original source code for MAGNET.
- `Dockerfile`: Containerized environment for running MAGNET with its specific dependencies (Python 3.8 + requirements).
- `tool.py`: The unified orchestrator script that mounts the dataset, builds/runs the Docker container, and parses MAGNET's raw output into the standard `output.json`.

## Usage
MAGNET expects an `inventory_kdm.xmi` file to exist in your dataset.
Execute the orchestrator using `uv`:

```bash
uv run tool.py \
  --dataset-path ../../datasets/<dataset-name> \
  --output-path ./outputs/<dataset-name>
```
