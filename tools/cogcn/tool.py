# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from cogcn_adapter import build_cogcn_inputs  # noqa: E402

TOOL = "CoGCN"
SRC = os.path.join(HERE, "cogcn", "cogcn")      # the upstream package dir (train.py, model.py, ...)
IMAGE = "sota-cogcn"
STOCK_K = 6                                      # train.py's default --k


def write_error(output_path, message):
    os.makedirs(output_path, exist_ok=True)
    with open(os.path.join(output_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"error": message, "tool": TOOL}, f, indent=4)
    print(f"Error written to {output_path}/output.json: {message}", file=sys.stderr)
    return 1


def membership_to_microservices(classes, labels):
    """k-means label per class row -> {"microservice_N": sorted classes}, clusters in label order."""
    groups = {}
    for cls, label in zip(classes, labels):
        groups.setdefault(int(label), []).append(cls)
    return {f"microservice_{i}": sorted(groups[l]) for i, l in enumerate(sorted(groups), 1)}


def docker_command(repo, args):
    """docker run for `args` inside the mounted repo copy, as the calling user (see tools/chgnn/tool.py)."""
    user = ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []
    return ["docker", "run", "--rm", "--platform", "linux/amd64"] + user + [
        "-v", f"{repo}:/workspace/cogcn", "-w", "/workspace/cogcn", IMAGE, "python"] + args


def run_train(repo, data_arg, k, runner):
    args = ["run_cogcn.py", "--dataset-str", data_arg, "--k", str(k)]
    if runner == "docker":
        if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
            subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", IMAGE, HERE], check=True)
        return subprocess.run(docker_command(repo, args), capture_output=True, text=True)
    return subprocess.run([sys.executable] + args, cwd=repo, capture_output=True, text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tool: CoGCN (Desai et al., AAAI 2021)")
    parser.add_argument("--dataset-path", required=True, help="Dataset directory (contains dataset.json)")
    parser.add_argument("--output-path", required=True, help="Directory for output.json and raw files")
    parser.add_argument("--k", type=int, default=STOCK_K, help=f"Number of clusters (train.py's stock default {STOCK_K})")
    parser.add_argument("--runner", choices=["docker", "local"], default="docker",
                        help="docker (default) or a local python env with the CoGCN deps")
    args = parser.parse_args(argv)

    ds_path = os.path.abspath(args.dataset_path)
    out_path = os.path.abspath(args.output_path)
    name = os.path.basename(ds_path.rstrip("/"))

    dataset_json = os.path.join(ds_path, "dataset.json")
    if not os.path.exists(dataset_json):
        return write_error(out_path, f"dataset.json not found in {ds_path}")
    with open(dataset_json, encoding="utf-8") as f:
        dataset = json.load(f)
    if not dataset.get("classes") and not dataset.get("methods"):
        return write_error(out_path, f"dataset '{name}' has no Java classes in dataset.json: cell is N/A")
    if not os.path.isfile(os.path.join(SRC, "train.py")):
        return write_error(out_path, "CoGCN submodule is empty: run `git submodule update --init`")
    n_classes = len(set(dataset.get("classes", ())) | {m.rsplit(".", 1)[0] for m in dataset.get("methods", {})})
    if args.k > n_classes:
        return write_error(out_path, f"--k {args.k} exceeds the {n_classes} classes of '{name}'")

    os.makedirs(out_path, exist_ok=True)
    # inside the output folder, not /tmp: Snap-packaged Docker cannot see /tmp, so a mount from there is empty
    with tempfile.TemporaryDirectory(dir=out_path, prefix="work-") as work:
        repo = os.path.join(work, "cogcn")
        shutil.copytree(SRC, repo, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(HERE, "run_cogcn.py"), repo)
        data_arg = os.path.join("data", "apps", name)
        info = build_cogcn_inputs(dataset, os.path.join(repo, data_arg))
        proc = run_train(repo, data_arg, args.k, args.runner)
        with open(os.path.join(out_path, "train.log"), "w", encoding="utf-8") as f:
            f.write(proc.stdout + proc.stderr)
        membership_file = os.path.join(repo, data_arg, "membership.json")
        if proc.returncode != 0 or not os.path.exists(membership_file):
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            return write_error(out_path, f"CoGCN run failed (exit {proc.returncode}): " + " | ".join(tail))
        with open(membership_file, encoding="utf-8") as f:
            labels = json.load(f)
        shutil.copy(membership_file, out_path)
        shutil.copy(os.path.join(repo, data_arg, "classes.txt"), out_path)
        with open(os.path.join(repo, data_arg, "classes.txt"), encoding="utf-8") as f:
            classes = f.read().split()

    microservices = membership_to_microservices(classes, labels)
    with open(os.path.join(out_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"tool": TOOL, "microservices": microservices}, f, indent=4)
    with open(os.path.join(out_path, "run_info.json"), "w", encoding="utf-8") as f:
        json.dump({**info, "k": args.k}, f, indent=4)
    print(f"CoGCN: {len(microservices)} microservices (k={args.k}) -> {out_path}/output.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
