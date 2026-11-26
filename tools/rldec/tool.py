# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "numpy",
#     "pandas",
#     "pyarrow",
# ]
# ///

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rldec_adapter import build_rldec_inputs, collect_classes  # noqa: E402

TOOL = "RLDec"
REPO = os.path.join(HERE, "decomp-rldec")
IMAGE = "sota-rldec"
DEFAULT_APPROACH = "combsequential"
DEFAULT_FEATURE = "structural"
DEFAULT_ITERATIONS = 20
DEFAULT_EPISODES = 1
DEFAULT_STRATEGY = "last"


def write_error(output_path, message):
    os.makedirs(output_path, exist_ok=True)
    with open(os.path.join(output_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"error": message, "tool": TOOL}, f, indent=4)
    print(f"Error written to {output_path}/output.json: {message}", file=sys.stderr)
    return 1


def partitions_to_microservices(raw):
    """RLDec's {'partition_<id>': [class FQNs]} -> {'microservice_N': sorted classes}, skipping empty and -1 outliers."""
    clusters = raw.get("microservices", raw) if isinstance(raw, dict) else {}
    entries = []
    for key, members in clusters.items():
        if not members:
            continue
        match = re.fullmatch(r"partition_(-?\d+(?:\.\d+)?)", str(key))
        if match:
            num = float(match.group(1))
            if int(num) == -1:
                continue
            sort_key = (0, num, str(key))
        else:
            sort_key = (1, 0.0, str(key))
        entries.append((sort_key, sorted(str(m) for m in members)))
    entries.sort(key=lambda item: item[0])
    return {f"microservice_{i}": members for i, (_, members) in enumerate(entries, 1)}


def docker_command(repo, args):
    """docker run for `args` inside the mounted repo copy, as the calling user (Snap-Docker safe)."""
    user = ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []
    return ["docker", "run", "--rm", "--platform", "linux/amd64"] + user + [
        "-v", f"{repo}:/workspace/rldec", "-w", "/workspace/rldec", IMAGE, "python"] + args


def build_run_args(app, n_classes, approach=DEFAULT_APPROACH, feature=DEFAULT_FEATURE,
                   iterations=DEFAULT_ITERATIONS, episodes=DEFAULT_EPISODES,
                   strategy=DEFAULT_STRATEGY, seed=None):
    args = [
        "run_rldec.py",
        "--app", app,
        "--data-dir", "data",
        "--models-dir", "trained_models",
        "--out-dir", "out",
        "--approach", approach,
        "--feature", feature,
        "--iterations", str(iterations),
        "--episodes", str(episodes),
        "--strategy", strategy,
        "--n-classes", str(n_classes),
    ]
    if seed is not None:
        args.extend(["--seed", str(seed)])
    return args


def run_rldec(repo, cli_args, runner):
    if runner == "docker":
        if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
            subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", IMAGE, HERE], check=True)
        return subprocess.run(docker_command(repo, cli_args), capture_output=True, text=True)
    if runner == "uv":
        uv = shutil.which("uv") or "uv"
        return subprocess.run([uv, "run", "--python", "3.10"] + cli_args, cwd=repo, capture_output=True, text=True)
    return subprocess.run([sys.executable] + cli_args, cwd=repo, capture_output=True, text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tool: RLDec (Sellami & Saied, EMSE 2025)")
    parser.add_argument("--dataset-path", required=True, help="Dataset directory (contains dataset.json)")
    parser.add_argument("--output-path", required=True, help="Directory for output.json and raw files")
    parser.add_argument("--approach", choices=["combsequential", "sequential", "flattened"],
                        default=DEFAULT_APPROACH, help="RLDec environment variant (default: combsequential)")
    parser.add_argument("--feature", choices=["structural", "semantic"], default=DEFAULT_FEATURE,
                        help="Feature matrix for sequential/flattened (ignored by combsequential)")
    parser.add_argument("--iterations", type=int, default=DEFAULT_ITERATIONS,
                        help=f"DQN training iterations (default: {DEFAULT_ITERATIONS})")
    parser.add_argument("--episodes", type=int, default=DEFAULT_EPISODES,
                        help=f"Decomposition rollout episodes (default: {DEFAULT_EPISODES})")
    parser.add_argument("--strategy", choices=["last", "best"], default=DEFAULT_STRATEGY,
                        help="Episode selection strategy during decomposition")
    parser.add_argument("--seed", type=int, default=None, help="Optional RLlib DQN seed")
    parser.add_argument("--runner", choices=["uv", "local", "docker"], default="uv",
                        help="uv (default, Python 3.10 PEP 723), local python, or docker (sota-rldec)")
    args = parser.parse_args(argv)

    ds_path = os.path.abspath(args.dataset_path)
    out_path = os.path.abspath(args.output_path)
    name = os.path.basename(ds_path.rstrip("/"))

    dataset_json = os.path.join(ds_path, "dataset.json")
    if not os.path.exists(dataset_json):
        return write_error(out_path, f"dataset.json not found in {ds_path}")
    with open(dataset_json, encoding="utf-8") as f:
        dataset = json.load(f)

    classes = collect_classes(dataset)
    if not classes:
        return write_error(out_path, f"dataset '{name}' has no Java classes in dataset.json: cell is N/A")
    if len(classes) < 2:
        return write_error(out_path, f"dataset '{name}' has fewer than 2 Java classes ({len(classes)}): cell is N/A")
    if not os.path.isfile(os.path.join(REPO, "rldec", "train_model.py")):
        return write_error(out_path, "RLDec submodule is empty: run `git submodule update --init`")

    os.makedirs(out_path, exist_ok=True)
    # inside the output folder, not /tmp: Snap-packaged Docker cannot see /tmp, so a mount from there is empty
    with tempfile.TemporaryDirectory(dir=out_path, prefix="work-") as work:
        repo = os.path.join(work, "decomp-rldec")
        shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        shutil.copy(os.path.join(HERE, "run_rldec.py"), repo)
        data_dir = os.path.join(repo, "data", name)
        info = build_rldec_inputs(dataset, ds_path, data_dir)
        cli_args = build_run_args(
            app=name,
            n_classes=len(classes),
            approach=args.approach,
            feature=args.feature,
            iterations=args.iterations,
            episodes=args.episodes,
            strategy=args.strategy,
            seed=args.seed,
        )
        proc = run_rldec(repo, cli_args, args.runner)
        with open(os.path.join(out_path, "train.log"), "w", encoding="utf-8") as f:
            f.write((proc.stdout or "") + (proc.stderr or ""))

        raw_decomp = os.path.join(repo, "out", "decomposition.json")
        raw_out = os.path.join(repo, "out", "output.json")
        if proc.returncode != 0 or (not os.path.exists(raw_decomp) and not os.path.exists(raw_out)):
            tail = ((proc.stderr or "") or (proc.stdout or "")).strip().splitlines()[-3:]
            return write_error(out_path, f"RLDec run failed (exit {proc.returncode}): " + " | ".join(tail))

        if os.path.exists(raw_decomp):
            shutil.copy(raw_decomp, os.path.join(out_path, "decomposition.json"))
            with open(raw_decomp, encoding="utf-8") as f:
                raw = json.load(f)
            microservices = partitions_to_microservices(raw)
        else:
            with open(raw_out, encoding="utf-8") as f:
                raw = json.load(f)
            microservices = raw.get("microservices") or partitions_to_microservices(raw)

        meta = {}
        meta_file = os.path.join(repo, "out", "run_meta.json")
        if os.path.exists(meta_file):
            with open(meta_file, encoding="utf-8") as f:
                meta = json.load(f)

    if not microservices:
        return write_error(out_path, "RLDec produced no non-outlier microservice partitions")

    with open(os.path.join(out_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"tool": TOOL, "microservices": microservices}, f, indent=4)
    run_info = {
        **info,
        **meta,
        "approach": args.approach,
        "feature": args.feature if args.approach != "combsequential" else ["structural", "semantic"],
        "iterations": args.iterations,
        "episodes": args.episodes,
        "strategy": args.strategy,
        "seed": args.seed,
        "runner": args.runner,
    }
    with open(os.path.join(out_path, "run_info.json"), "w", encoding="utf-8") as f:
        json.dump(run_info, f, indent=4)
    print(f"RLDec: {len(microservices)} microservices ({args.approach}, iters={args.iterations}) -> {out_path}/output.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
