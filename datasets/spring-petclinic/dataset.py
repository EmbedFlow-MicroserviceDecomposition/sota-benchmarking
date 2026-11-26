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
    parser = argparse.ArgumentParser(description="Dataset: Monolith Adapter for Spring PetClinic")
    parser.add_argument("--source_dir", type=str, default="spring-petclinic", help="Path to monolithic source code")
    parser.add_argument("--output", type=str, default="dataset.json", help="Output path for Universal JSON")
    args = parser.parse_args()

    build_dataset("Spring PetClinic", args.source_dir, args.output, "spring-petclinic/target/spring-petclinic-1.5.1.jar", "spring-petclinic_kdm.xmi")
