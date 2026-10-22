# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import argparse
import gzip
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fosci_preprocess  # noqa: E402

TOOL = "FoSCI"
AUTHORS_TRACES = os.path.join(HERE, "FoSCI", "traces")
# execution traces published by the FoSCI authors (git-lfs files in the FoSCI repo), by dataset
AUTHOR_FILES = {"jpetstore": "jpetstore.txt", "spring-blog": "springblog.txt",
                "jforum": "jforum.txt", "apache-roller": "roller.txt"}
STOCK_N = 10  # fosci-wrap's PARTITION_K
# per-subject service counts: midpoints of the paper's ranges (Section 4.6: SpringBlog 6-10, JForum 7-11, Roller 14-18),
# and autocare, where N=10 stalled against its 12 atoms
PAPER_N = {"spring-blog": 8, "jforum": 9, "apache-roller": 16, "autocare": 8}


class TraceError(Exception):
    pass


def write_error(output_path, message):
    os.makedirs(output_path, exist_ok=True)
    with open(os.path.join(output_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"error": message, "tool": TOOL}, f, indent=4)
    print(f"Error written to {output_path}/output.json: {message}", file=sys.stderr)
    return 1


def choose_n(name, atoms, override=None):
    """Service-candidate count N, or None when there are too few atoms to partition.

    N must stay below the number of functional atoms (N close to it never converges: a bear-board run hung for 4+ CPU
    hours at N=10 on 5 atoms), so the default is min(per-dataset N, atoms - 2).
    """
    if override is not None:
        if override >= atoms:
            raise ValueError(f"--n-services {override} must be below the number of functional atoms ({atoms})")
        return override
    if atoms - 2 < 2:
        return None
    return min(PAPER_N.get(name, STOCK_N), atoms - 2)


def find_trace(name, dataset_path):
    """Raw trace file for a dataset: datasets/<name>/fosci_trace.csv.gz, else the authors' trace."""
    own = os.path.join(dataset_path, "fosci_trace.csv.gz")
    if os.path.exists(own):
        return own
    authors = AUTHOR_FILES.get(name)
    if authors:
        path = os.path.join(AUTHORS_TRACES, authors)
        if os.path.exists(path):
            with open(path, "rb") as f:
                if f.read(40).startswith(b"version https://git-lfs"):
                    raise TraceError(f"the authors' trace {path} is a git-lfs pointer: run "
                                     f"`cd {os.path.dirname(AUTHORS_TRACES)} && git lfs pull --include=traces/{authors}`")
            return path
    raise TraceError(f"no execution trace for dataset '{name}' (datasets/{name}/fosci_trace.csv.gz or the FoSCI "
                     "authors' traces): FoSCI is trace-based; cell is N/A")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tool: FoSCI (Jin et al., TSE 2019), via fosci-wrap")
    parser.add_argument("--dataset-path", required=True, help="Dataset directory (contains dataset.json)")
    parser.add_argument("--output-path", required=True, help="Directory for output.json and raw files")
    parser.add_argument("--n-services", type=int, default=None, help="Service-candidate count N (default: per dataset)")
    parser.add_argument("--seed", type=int, default=None, help="Seed for the NSGA-II search (default: random, recorded)")
    parser.add_argument("--timeout", type=int, default=6 * 3600, help="Seconds before the search is abandoned")
    args = parser.parse_args(argv)

    ds_path = os.path.abspath(args.dataset_path)
    out_path = os.path.abspath(args.output_path)
    name = os.path.basename(ds_path.rstrip("/"))

    if not os.path.exists(os.path.join(ds_path, "dataset.json")):
        return write_error(out_path, f"dataset.json not found in {ds_path}")
    try:
        trace = find_trace(name, ds_path)
    except TraceError as e:
        return write_error(out_path, str(e))

    os.makedirs(out_path, exist_ok=True)
    seed = args.seed if args.seed is not None else random.SystemRandom().randrange(2 ** 31)
    with tempfile.TemporaryDirectory() as work:
        info = fosci_preprocess.write_inputs(trace, work)
        atoms_csv, n_atoms = fosci_preprocess.generate_atoms(os.path.join(work, "workflow_reduced.csv"), work)
        try:
            n = choose_n(name, n_atoms, args.n_services)
        except ValueError as e:
            return write_error(out_path, str(e))
        if n is None:
            return write_error(out_path, f"only {n_atoms} functional atoms after trace reduction (diff=3): too few "
                                         "to partition into services; cell is N/A")
        result = os.path.join(work, "result.json")
        try:
            proc = subprocess.run(
                [sys.executable, os.path.join(HERE, "run_nsga.py"), "--atoms", atoms_csv,
                 "--calldep", os.path.join(work, "calldep.csv"), "--concerndep", os.path.join(work, "concerndep.csv"),
                 "--out", result, "--k", str(n), "--seed", str(seed)],
                capture_output=True, text=True, timeout=args.timeout)
        except subprocess.TimeoutExpired:
            return write_error(out_path, f"NSGA-II search exceeded {args.timeout}s (N={n}, {n_atoms} atoms)")
        with open(os.path.join(out_path, "fosci.log"), "w", encoding="utf-8") as f:
            f.write(proc.stdout + proc.stderr)
        if proc.returncode != 0 or not os.path.exists(result):
            return write_error(out_path, f"fosci-wrap failed (exit {proc.returncode}): "
                                         + " | ".join((proc.stderr or proc.stdout).strip().splitlines()[-2:]))
        shutil.copy(atoms_csv, out_path)
        with open(result, encoding="utf-8") as f:
            clusters = json.load(f)

    microservices = {f"microservice_{i}": sorted(clusters[cid])
                     for i, cid in enumerate(sorted(clusters, key=lambda c: (not c.isdigit(), int(c) if c.isdigit() else 0, c)), 1)}
    with open(os.path.join(out_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"tool": TOOL, "microservices": microservices}, f, indent=4)
    with open(os.path.join(out_path, "run_info.json"), "w", encoding="utf-8") as f:
        json.dump({**info, "atoms": n_atoms, "n_services": n, "seed": seed, "trace": os.path.relpath(trace, ds_path)
                   if trace.startswith(ds_path) else os.path.basename(trace)}, f, indent=4)
    print(f"FoSCI: {len(microservices)} microservices (N={n}, {n_atoms} atoms, seed={seed}) -> {out_path}/output.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
