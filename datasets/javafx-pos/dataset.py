# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
# Needs JDK 17+ and Maven: the shared JavaParser extractor (datasets/extractor) is built on first run.

import os
import sys
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import build_dataset  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dataset: Monolith Adapter for JavaFX-POS")
    parser.add_argument("--source_dir", type=str, default="JavaFX-Point-of-Sales", help="Path to monolithic source code")
    parser.add_argument("--output", type=str, default="dataset.json", help="Output path for Universal JSON")
    args = parser.parse_args()

    build_dataset("JavaFX-POS", args.source_dir, args.output, "JavaFX-Point-of-Sales/target/inventory-1.0.jar", "javafx-pos_kdm.xmi")
