# Acme Air Dataset

This directory contains the monolithic dataset and adapter for **Acme Air**.
The original application is tracked as a Git submodule in the `acmeair/` directory.

## Structure
- `acmeair/`: Git submodule containing the Acme Air monolithic source code.
- `dataset.py`: Python script utilizing `javalang` to traverse the `acmeair` source code, extract all class/method signatures, and locate the required `inventory_kdm.xmi`. It outputs this structured data to `dataset.json`.
- `.gitignore`: Ignores the generated `dataset.json`.

## Usage
Run the adapter script using `uv`:

```bash
uv run dataset.py
```
