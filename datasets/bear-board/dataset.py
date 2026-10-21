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
    parser = argparse.ArgumentParser(description="Dataset: Monolith Adapter for Bear Board")
    parser.add_argument("--source_dir", type=str, default="bear-board", help="Path to monolithic source code")
    parser.add_argument("--output", type=str, default="dataset.json", help="Output path for Universal JSON")
    args = parser.parse_args()

    build_dataset("Bear Board", args.source_dir, args.output, "bear-board/target/bear-board.jar", "bear-board_kdm.xmi")
