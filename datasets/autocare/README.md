# AutoCare Nepal Dataset

This directory contains the monolithic dataset and adapter for **AutoCare Nepal**, an open-source Java application.

The original monolithic application is tracked as a Git submodule in the `autocare-nepal/` directory.

## Structure
- `autocare-nepal/`: Git submodule containing the monolithic source code.
- `dataset.py`: Python script utilizing `javalang` to traverse the Java source code, extract all class/method signatures, and locate the required `autocare_kdm.xmi`. It outputs this structured data to `dataset.json`.

## Eclipse MoDisco Generation (FAILED)

**Warning:** Eclipse MoDisco fails to successfully generate the KDM Code Model (`_kdm.xmi`) for this specific codebase. 

As with other specific datasets in this repository, MoDisco's internal AST generation and ATL KDM transformation processes break down on this repository.

Because MoDisco cannot process the source code into a valid KDM model, decomposition tools that strictly rely on MoDisco's KDM schema (like MAGNET) cannot natively evaluate this dataset. Any evaluation requires an alternative Call Graph generator to artificially synthesize the required `autocare_kdm.xmi`.

## Usage

You can still run the adapter script to extract the method dataset via `javalang`:

```bash
uv run dataset.py
```

This will parse the raw Java files and output `dataset.json`, which can be used by tools that do not require KDM input.
