# Bear Board Dataset

This directory contains the monolithic dataset and adapter for **Bear Board**, an open-source Java application.

The original monolithic application is tracked as a Git submodule in the `bear-board/` directory.

## Structure
- `bear-board/`: Git submodule containing the monolithic source code.
- `dataset.py`: Python script utilizing `javalang` to traverse the Java source code, extract all class/method signatures, and locate the required `bear-board_kdm.xmi`. It outputs this structured data to `dataset.json`.

## Eclipse MoDisco Generation (FAILED)

**Warning:** Eclipse MoDisco fails to successfully generate the KDM Code Model (`_kdm.xmi`) for this specific codebase. 

As with other specific datasets in this repository (like JForum and JavaFX-POS), MoDisco's internal AST generation and ATL KDM transformation processes break down on this repository (usually resulting in an ATL `VMException` or `DanglingHREFException`).

Because MoDisco cannot process the source code into a valid KDM model, decomposition tools that strictly rely on MoDisco's KDM schema (like MAGNET) cannot natively evaluate this dataset. Any evaluation requires an alternative Call Graph generator to artificially synthesize the required `bear-board_kdm.xmi`.

## Usage

You can still run the adapter script to extract the method dataset via `javalang`:

```bash
uv run dataset.py
```

This will parse the raw Java files and output `dataset.json`, which can be used by tools that do not require KDM input.
