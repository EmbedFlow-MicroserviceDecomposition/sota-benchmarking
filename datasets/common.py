"""Shared dataset.json generation: runs the JavaParser extractor and merges usecases.json."""

import json
import os
import shutil
import subprocess
import sys
import tempfile

EXTRACTOR_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extractor")
EXTRACTOR_JAR = os.path.join(EXTRACTOR_DIR, "target", "extractor.jar")


def ensure_extractor():
    """Return the extractor jar path, building it with Maven on first use."""
    if os.path.exists(EXTRACTOR_JAR):
        return EXTRACTOR_JAR
    if not shutil.which("mvn"):
        sys.exit("extractor.jar is missing and Maven (mvn) is not installed; see datasets/extractor/README.md")
    print("Building datasets/extractor ...")
    subprocess.run(["mvn", "-q", "-DskipTests", "package"], cwd=EXTRACTOR_DIR, check=True)
    return EXTRACTOR_JAR


def build_dataset(dataset_name, source_dir, output_file, build_path, xmi_path):
    """Write dataset.json for `source_dir`; exits non-zero (writing nothing) if any file fails to parse."""
    out_dir = os.path.dirname(os.path.abspath(output_file))
    # a relative source_dir that is not under the cwd is taken relative to the output directory
    if not os.path.isabs(source_dir) and not os.path.exists(source_dir):
        source_dir = os.path.join(out_dir, source_dir)
    source_dir = os.path.abspath(source_dir)

    os.makedirs(out_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        raw = os.path.join(tmp, "dataset.json")
        proc = subprocess.run(
            ["java", "-jar", ensure_extractor(),
             "--source", source_dir, "--out", raw, "--dataset", dataset_name,
             "--build-path", build_path, "--xmi-path", xmi_path,
             "--source-path", os.path.relpath(source_dir, out_dir)],
            capture_output=True, text=True)
        sys.stdout.write(proc.stdout)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            sys.exit(proc.returncode)
        with open(raw, encoding="utf-8") as f:
            data = json.load(f)

    usecases_path = os.path.join(out_dir, "usecases.json")
    data["usecases"] = {}
    if os.path.exists(usecases_path):
        with open(usecases_path, encoding="utf-8") as f:
            data["usecases"] = json.load(f)

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    print(f"Universal JSON saved to {output_file}")
