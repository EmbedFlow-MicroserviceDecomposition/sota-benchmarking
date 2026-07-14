# JavaFX Point of Sales Dataset

This directory contains the monolithic dataset and adapter for **JavaFX Point of Sales**, an open-source Java Desktop POS application.

The original monolithic application is tracked as a Git submodule in the `JavaFX-Point-of-Sales/` directory.

## Structure
- `JavaFX-Point-of-Sales/`: Git submodule containing the monolithic source code.
- `dataset.py`: Python script utilizing `javalang` to traverse the Java source code, extract all class/method signatures, and locate the required `javafx-pos_kdm.xmi`. It outputs this structured data to `dataset.json`.

## Eclipse MoDisco Generation (FAILED)

**Warning:** Similar to JForum, Eclipse MoDisco fails to successfully generate the KDM Code Model (`_kdm.xmi`) for this specific codebase. 

While the exact nature of the failure may vary (often related to unresolved JavaFX UI bindings or the ATL transformer `VMException`), it has been documented that MoDisco's internal model generation and KDM transformation processes break down on this repository.

Because MoDisco cannot process the source code into a valid KDM model, decomposition tools that strictly rely on MoDisco's KDM schema (like MAGNET) cannot natively evaluate this dataset. Any evaluation requires an alternative Call Graph generator to artificially synthesize the required `javafx-pos_kdm.xmi`.

## Usage

You can still run the adapter script to extract the method dataset via `javalang`:

```bash
uv run dataset.py
```

This will parse the raw Java files and output `dataset.json`, which can be used by tools that do not require KDM input.
