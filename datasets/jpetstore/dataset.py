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
    parser = argparse.ArgumentParser(description="Dataset: Monolith Adapter for JPetStore")
    parser.add_argument("--source_dir", type=str, default="jpetstore-6", help="Path to monolithic source code")
    parser.add_argument("--output", type=str, default="dataset.json", help="Output path for Universal JSON")
    args = parser.parse_args()

    build_dataset("JPetStore", args.source_dir, args.output, "jpetstore/target/jpetstore.war", "jpetstore_kdm.xmi")
