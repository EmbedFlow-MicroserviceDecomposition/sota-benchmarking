# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = [
#     "Click>=8.0.4",
#     "neomodel<5",
#     "setuptools<81",
#     "simple-ddl-parser==0.25.0",
#     "PyYAML>=6.0",
#     "pandas>=1.4.1",
#     "tqdm>=4.63.0",
#     "networkx>=2.7.1",
#     "scipy>=1.8.0",
#     "py2neo>=2021.2.3",
#     "tabulate>=0.8.10",
#     "numpy",
#     "ipdb>=0.13.9",
# ]
# ///

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = "CARGO"
DGI_SRC = os.path.join(HERE, "tackle-data-gravity-insights", "dgi")
PATCH = os.path.join(HERE, "patches", "dgi-robustness.patch")
FACTS_ROOT = os.path.join(HERE, "doop-data")          # git-ignored cache: Doop fact directories, one per dataset
TRANSACTIONS = os.path.join(HERE, "transactions")      # Tackle-DiVA output, where one exists (daytrader)
CONTAINER = "sota-cargo-neo4j"
BOLT = ("bolt://localhost:7687", ("neo4j", "tackle"))
# the paper's RQ3 protocol (Section 4.1/5.3): K = 3..13 x 5 seeds, averaged rather than swept-and-selected
DEFAULT_KS, DEFAULT_SEEDS = "3,5,7,9,11,13", "42,43,44,45,46"


def write_error(output_path, message):
    os.makedirs(output_path, exist_ok=True)
    with open(os.path.join(output_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"error": message, "tool": TOOL}, f, indent=4)
    print(f"Error written to {output_path}/output.json: {message}", file=sys.stderr)
    return 1


def partition_to_microservices(parts):
    """CARGO's {class: partition id} -> {"microservice_N": sorted classes}; '$' inner-class separator becomes '.'."""
    groups = {}
    for cls, pid in parts.items():
        groups.setdefault(int(pid), []).append(cls.replace("$", "."))
    return {f"microservice_{i}": sorted(groups[pid]) for i, pid in enumerate(sorted(groups), 1)}


def parse_grid(ks, seeds):
    """[(K, seed)] in the order the paper's protocol runs them: seed-major."""
    return [(int(k), int(s)) for s in seeds.split(",") for k in ks.split(",")]


def ensure_neo4j():
    """Start (or reuse) the Neo4j container dgi stores its graph in."""
    names = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}} {{.Status}}"], capture_output=True, text=True)
    if names.returncode != 0:
        raise RuntimeError("docker is not available: start Docker Desktop (or pass --neo4j external)")
    line = next((l for l in names.stdout.splitlines() if l.split()[0] == CONTAINER), None)
    if line is None:
        subprocess.run(["docker", "run", "-d", "--name", CONTAINER, "-p", "7474:7474", "-p", "7687:7687",
                        "-e", "NEO4J_AUTH=neo4j/tackle",
                        "-e", "NEO4J_dbms_security_auth__minimum__password__length=1",  # 'tackle' is 6 chars
                        "neo4j:5"], check=True, capture_output=True)
    elif "Up" not in line:
        subprocess.run(["docker", "start", CONTAINER], check=True, capture_output=True)


def wait_for_neo4j(timeout=180):
    from py2neo import Graph

    deadline = time.time() + timeout
    while True:
        try:
            Graph(BOLT[0], auth=BOLT[1]).run("RETURN 1").evaluate()
            return
        except Exception:
            if time.time() > deadline:
                raise RuntimeError("Neo4j did not become ready")
            time.sleep(3)


def prepare_dgi(work):
    """Copy the pristine dgi package and apply the robustness patch (the submodule stays clean)."""
    shutil.copytree(DGI_SRC, os.path.join(work, "dgi"), ignore=shutil.ignore_patterns("__pycache__"))
    subprocess.run(["patch", "-p1", "-d", work, "-i", PATCH], check=True, capture_output=True)
    sys.path.insert(0, work)


def load_graph(name, facts_dir, transactions):
    """Load the Doop facts (and DiVA transactions) into Neo4j unless this dataset is already there."""
    from py2neo import Graph

    graph = Graph(BOLT[0], auth=BOLT[1])
    marker = graph.run("MATCH (m:SotaMarker) RETURN m.dataset AS d, m.facts AS f").data()
    if marker and marker[0]["d"] == name and marker[0]["f"] == facts_dir:
        print(f"Neo4j already holds the SDG of {name}")
        return
    from dgi.cli import cli

    graph.run("MATCH (n) DETACH DELETE n")
    cli.main(args=["-c", "c2g", "-i", facts_dir], standalone_mode=False)
    if transactions:
        cli.main(args=["tx2g", "-i", transactions], standalone_mode=False)
    graph.run("CREATE (:SotaMarker {dataset: $d, facts: $f})", d=name, f=facts_dir)


def run_cargo(name, grid, out_path):
    import networkx as nx
    import numpy as np
    from dgi.cargo.cargo import Cargo

    cargo = Cargo(name)
    runs = []
    for k, seed in grid:
        random.seed(seed)
        np.random.seed(seed)
        graph = cargo.do_cargo("unique", k, None)
        microservices = partition_to_microservices(nx.get_node_attributes(graph, "partition"))
        run_dir = os.path.join(out_path, "runs", f"k{k}_seed{seed}")
        os.makedirs(run_dir, exist_ok=True)
        with open(os.path.join(run_dir, "output.json"), "w", encoding="utf-8") as f:
            json.dump({"tool": TOOL, "microservices": microservices}, f, indent=4)
        runs.append({"k": k, "seed": seed, "microservices": len(microservices),
                     "classes": sum(len(v) for v in microservices.values())})
        print(f"CARGO K={k} seed={seed}: {len(microservices)} microservices")
    return runs


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tool: CARGO (Nitin et al., ASE 2022), from cached Doop facts")
    parser.add_argument("--dataset-path", required=True, help="Dataset directory (contains dataset.json)")
    parser.add_argument("--output-path", required=True, help="Directory for output.json, runs/ and raw files")
    parser.add_argument("--facts-dir", default=None, help="Doop fact directory (default: tools/cargo/doop-data/<dataset>)")
    parser.add_argument("--k", default=DEFAULT_KS, help="Comma-separated partition counts K (default: the paper's 3..13)")
    parser.add_argument("--seeds", default=DEFAULT_SEEDS, help="Comma-separated seeds (default: 42..46)")
    parser.add_argument("--neo4j", choices=["docker", "external"], default="docker",
                        help="docker (default) manages the sota-cargo-neo4j container; external uses localhost:7687")
    args = parser.parse_args(argv)

    ds_path = os.path.abspath(args.dataset_path)
    out_path = os.path.abspath(args.output_path)
    name = os.path.basename(ds_path.rstrip("/"))

    if not os.path.exists(os.path.join(ds_path, "dataset.json")):
        return write_error(out_path, f"dataset.json not found in {ds_path}")
    with open(os.path.join(ds_path, "dataset.json"), encoding="utf-8") as f:
        dataset = json.load(f)
    if not dataset.get("classes") and not dataset.get("methods"):
        return write_error(out_path, f"dataset '{name}' has no Java classes in dataset.json: cell is N/A")
    facts_dir = os.path.abspath(args.facts_dir or os.path.join(FACTS_ROOT, name))
    if not os.path.isdir(facts_dir) or not os.listdir(facts_dir):
        # deliberately not worded "N/A": a missing input is a failure to fix, and `benchmark.py run` retries such cells
        return write_error(out_path, f"no Doop facts for dataset '{name}' at {facts_dir}: CARGO analyses compiled bytecode "
                                     "with Doop first; copy the facts there or produce them (see tools/cargo/README.md)")
    if not os.path.isdir(os.path.join(DGI_SRC, "cargo")):
        return write_error(out_path, "CARGO submodule is empty: run `git submodule update --init`")
    transactions = os.path.join(TRANSACTIONS, f"{name}.json")
    transactions = transactions if os.path.exists(transactions) else None
    grid = parse_grid(args.k, args.seeds)

    os.makedirs(out_path, exist_ok=True)
    with tempfile.TemporaryDirectory() as work:
        try:
            if args.neo4j == "docker":
                ensure_neo4j()
            wait_for_neo4j()
            prepare_dgi(work)
            load_graph(name, facts_dir, transactions)
            runs = run_cargo(name, grid, out_path)
        except Exception as e:  # tool failure is reported as an error cell, never a partial partition
            return write_error(out_path, f"CARGO run failed: {type(e).__name__}: {e}")

    shutil.copy(os.path.join(out_path, "runs", f"k{grid[0][0]}_seed{grid[0][1]}", "output.json"),
                os.path.join(out_path, "output.json"))
    with open(os.path.join(out_path, "run_info.json"), "w", encoding="utf-8") as f:
        json.dump({"facts_dir": facts_dir, "transactions": bool(transactions), "runs": runs}, f, indent=4)
    print(f"CARGO: {len(runs)} runs -> {out_path} (output.json = first run)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
