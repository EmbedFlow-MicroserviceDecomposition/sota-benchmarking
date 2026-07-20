# IBM Mono2Micro Tool

This directory contains the orchestrator for **IBM Mono2Micro**, an AI-driven, semi-automated tool designed by IBM Research for monolith-to-microservices decomposition.

## Overview
- **Official Page:** [IBM Mono2Micro](https://www.ibm.com/cloud/mono2micro)
- **Paper Data:** The data published in the original FSE 2021 paper can be found at the [Mono2Micro-FSE-2021 repository](https://github.com/kaliaanup/Mono2Micro-FSE-2021).

## Setup & Installation

Due to proprietary enterprise licensing, the Mono2Micro CLI binary **cannot** be redistributed in this repository. You must download and extract it manually.

### 1. Download the Tool
1. Visit the [IBM Mono2Micro Downloads](https://www.ibm.com/support/pages/ibm-mono2micro-downloads) page.
2. Accept the license agreement and download the CLI tool archive (e.g., `Mono2Micro-CLI.zip` or `.tar.gz`).

### 2. Extract the Tool
1. Extract the downloaded archive directly into this directory (`tools/mono2micro/`).
2. Rename the extracted folder to `Mono2Micro-CLI` (if it isn't already) so that the orchestrator script can find it. 
   - The path to the executable should be: `tools/mono2micro/Mono2Micro-CLI/mono2micro` (or `mono2micro.exe` on Windows).

*(Note: The `Mono2Micro-CLI/` directory is explicitly ignored by Git via the `.gitignore` in this folder to prevent accidental commits of proprietary IBM binaries.)*

## Usage

Mono2Micro requires a multi-step process involving static analysis, runtime instrumentation, use-case recording, and AI recommendation. 

We have provided a `tool.py` Python orchestrator to automate and guide you through this entire process interactively.

### 1. Configure the Dataset
Ensure that the `dataset.json` for your target application has the following properties:
- `source_path`: The path to the source code root (relative to the dataset directory).
- `build_path`: The path to the compiled, runnable `.jar` or `.war` file (relative to the dataset directory).

### 2. Run the Orchestrator
Execute the script using `uv`:

```bash
cd tools/mono2micro/
uv run tool.py --dataset-path ../../datasets/<dataset>/ --output-path outputs/<dataset>/
```

### 3. Follow Interactive Prompts
The orchestrator will automatically run the static analysis phase and construct the necessary `tables/` directories.

Because Mono2Micro requires dynamic trace data, the script will then **pause** and prompt you to open a second terminal. It will provide two exact commands for you to run:
1. **Instrument and run the monolith:** A `java -javaagent:...` command to launch your app.
2. **Start recording traces:** A `./mono2micro usecase ...` command to begin recording. Follow the interactive instructions provided by this command to execute and record your business use cases.

### 4. Finalizing
Once you have executed the use cases and generated the traces in the second terminal, press **Enter** in the original terminal.

The orchestrator will automatically:
1. Run the Mono2Micro AI Recommender.
2. Parse the output graph from `mono2micro-output/oriole/final_graph.json`.
3. Standardize the microservice partitions into a generic `output.json` for benchmark evaluation.
