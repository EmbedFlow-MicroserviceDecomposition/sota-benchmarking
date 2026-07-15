# CICS Genapp Dataset

This directory contains the monolithic dataset and adapter for **CICS Genapp**, an IBM General Insurance Application designed for CICS TS.

The original monolithic application is tracked as a Git submodule in the `cics-genapp/` directory.

## Structure
- `cics-genapp/`: Git submodule containing the monolithic source code.
- `dataset.py`: Python script to parse the source code and extract method signatures into `dataset.json`. 

## Eclipse MoDisco Generation (NOT APPLICABLE)

CICS Genapp is fundamentally a **COBOL** codebase designed for IBM Z mainframes. 

Since Eclipse MoDisco's Java Discoverer is strictly designed to parse Java Source Code, **KDM generation via Eclipse MoDisco is not applicable to this dataset.** Extracting a Call Graph for this application requires a specialized COBOL AST parser or mainframe discovery tool.

## Usage

You can technically run the adapter script:

```bash
uv run dataset.py
```

However, because the adapter utilizes `javalang` to scrape for Java methods, it will likely output 0 methods and an empty `dataset.json`. This script is provided primarily to maintain structural consistency across the automated evaluation pipeline.
