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
from chgnn_adapter import build_chgnn_inputs  # noqa: E402

TOOL = "CHGNN"
REPO = os.path.join(HERE, "Monolith-to-Microservices")
CONFIGS = os.path.join(HERE, "configs")
IMAGE = "sota-chgnn"
CODE = "with_edge_loss"
MODEL = "AE_EGCN_Separate"


def write_error(output_path, message):
    os.makedirs(output_path, exist_ok=True)
    with open(os.path.join(output_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"error": message, "tool": TOOL}, f, indent=4)
    print(f"Error written to {output_path}/output.json: {message}", file=sys.stderr)
    return 1


def clusters_to_microservices(raw):
    """CHGNN's {cluster_id: [class names + '<x>-res' resource nodes]} -> microservice_N lists of classes."""
    microservices = {}
    for cid in sorted(raw, key=lambda c: (not c.isdigit(), int(c) if c.isdigit() else 0, c)):
        classes = sorted(n for n in raw[cid] if not n.endswith("-res"))
        if classes:
            microservices[f"microservice_{len(microservices) + 1}"] = classes
    return microservices


def prepare_repo(work, slug, dataset, config_dir, entrypoints_file):
    """Copy the pristine submodule into `work` and place this dataset's CHGNN inputs in its data dir."""
    repo = os.path.join(work, "repo")
    shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns(".git"))
    shutil.copy(os.path.join(HERE, "run_chgnn.py"), repo)
    bundled = os.path.join(config_dir, "BUNDLED")
    if os.path.exists(bundled):
        # authors' own preparation shipped in the CHGNN repo (no seeds/db map exist for our checkout)
        slug = open(bundled).read().strip()
    else:
        data_dir = os.path.join(repo, "data_layer", "utilities", "data", f"{slug}_{MODEL}")
        build_chgnn_inputs(dataset, config_dir, data_dir, code=CODE, entrypoints_file=entrypoints_file)
    return repo, slug


def docker_command(repo, args):
    """docker run for `args` inside the mounted repo copy, as the calling user: a root container would leave root-owned files in
    the temp directory, which the tool could then not remove (Linux; Docker Desktop on macOS hides this)."""
    user = ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []
    return ["docker", "run", "--rm", "--platform", "linux/amd64"] + user + [
        "-v", f"{repo}:/workspace/chgnn", "-w", "/workspace/chgnn", IMAGE, "python"] + args


def run_chgnn(repo, slug, runner):
    args = ["run_chgnn.py", f"--model={MODEL}", f"--data={slug}", f"--code={CODE}"]
    if runner == "docker":
        if subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True).returncode != 0:
            subprocess.run(["docker", "build", "--platform", "linux/amd64", "-t", IMAGE, HERE], check=True)
        return subprocess.run(docker_command(repo, args), capture_output=True, text=True)
    return subprocess.run([sys.executable] + args, cwd=repo, capture_output=True, text=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Tool: CHGNN (Mathai et al., IJCAI 2022)")
    parser.add_argument("--dataset-path", required=True, help="Dataset directory (contains dataset.json)")
    parser.add_argument("--output-path", required=True, help="Directory for output.json and raw CHGNN files")
    parser.add_argument("--runner", choices=["docker", "local"], default="docker",
                        help="docker (default) or a local python env that already has the CHGNN deps")
    args = parser.parse_args(argv)

    ds_path = os.path.abspath(args.dataset_path)
    out_path = os.path.abspath(args.output_path)
    name = os.path.basename(ds_path.rstrip("/"))

    dataset_json = os.path.join(ds_path, "dataset.json")
    if not os.path.exists(dataset_json):
        return write_error(out_path, f"dataset.json not found in {ds_path}")
    config_dir = os.path.join(CONFIGS, name)
    if not os.path.isdir(config_dir):
        return write_error(out_path, f"no CHGNN config for dataset '{name}' (tools/chgnn/configs/{name}/): "
                                     "CHGNN needs a DB map and seeds; cell is N/A")
    if not os.path.isdir(os.path.join(REPO, "data_layer")):
        return write_error(out_path, "CHGNN submodule is empty: run `git submodule update --init`")
    with open(dataset_json, encoding="utf-8") as f:
        dataset = json.load(f)

    os.makedirs(out_path, exist_ok=True)
    # inside the output folder, not /tmp: Snap-packaged Docker cannot see /tmp, so a mount from there is empty
    with tempfile.TemporaryDirectory(dir=out_path, prefix="work-") as work:
        try:
            repo, slug = prepare_repo(work, name.replace("-", "_"), dataset, config_dir,
                                      os.path.join(ds_path, "entrypoints.txt"))
        except ValueError as e:
            return write_error(out_path, str(e))
        proc = run_chgnn(repo, slug, args.runner)
        with open(os.path.join(out_path, "chgnn.log"), "w", encoding="utf-8") as f:
            f.write(proc.stdout + proc.stderr)
        data_dir = os.path.join(repo, "data_layer", "utilities", "data", f"{slug}_{MODEL}")
        clusters_file = os.path.join(data_dir, f"clusters_{CODE}.json")
        if proc.returncode != 0 or not os.path.exists(clusters_file):
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
            return write_error(out_path, f"CHGNN run failed (exit {proc.returncode}): " + " | ".join(tail))
        for rel in (f"clusters_{CODE}.json", "metrics.txt", os.path.join("custom", f"gcnconfig_{CODE}.json")):
            if os.path.exists(os.path.join(data_dir, rel)):
                shutil.copy(os.path.join(data_dir, rel), out_path)
        with open(clusters_file, encoding="utf-8") as f:
            raw = json.load(f)

    microservices = clusters_to_microservices(raw)
    if not microservices:
        return write_error(out_path, "CHGNN produced no clusters with classes")
    with open(os.path.join(out_path, "output.json"), "w", encoding="utf-8") as f:
        json.dump({"tool": TOOL, "microservices": microservices}, f, indent=4)
    print(f"CHGNN: {len(microservices)} microservices -> {out_path}/output.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
