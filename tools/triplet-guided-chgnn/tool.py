# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///

import os
import sys
import glob
import json
import shutil
import argparse
import subprocess
from generate_chgnn_graph import generate_chgnn_graph

def write_error(output_json_path, message):
    os.makedirs(os.path.dirname(output_json_path) or '.', exist_ok=True)
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump({"error": message, "tool": "TripletGuidedCHGNN"}, f, indent=4)
    print(f"Error written to {output_json_path}: {message}")
    sys.exit(1)

def build_class_lookup(dataset_path):
    class_map = {}
    if not dataset_path or not os.path.exists(dataset_path):
        return class_map

    ds_json = os.path.join(dataset_path, "dataset.json")
    if os.path.exists(ds_json):
        try:
            with open(ds_json, "r", encoding="utf-8") as f:
                d = json.load(f)
            for mid, mdata in d.get("methods", {}).items():
                pkg = mdata.get("package", "")
                cls = mdata.get("class", "")
                if cls and pkg:
                    class_map.setdefault(cls, set()).add(f"{pkg}.{cls}")
            for e in d.get("edges", []):
                for node in [e.get("src"), e.get("dst")]:
                    if node and "." in node and not node.startswith("java.") and not node.startswith("org.spring"):
                        simple = node.split(".")[-1]
                        class_map.setdefault(simple, set()).add(node)
        except Exception as e:
            print(f"Warning: could not read {ds_json}: {e}")

    for root, _, files in os.walk(dataset_path):
        for f in files:
            if f.endswith(".java"):
                full_path = os.path.join(root, f)
                simple = f[:-5]
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as jf:
                        for line in jf:
                            line = line.strip()
                            if line.startswith("package ") and line.endswith(";"):
                                pkg = line[8:-1].strip()
                                class_map.setdefault(simple, set()).add(f"{pkg}.{simple}")
                                break
                except Exception:
                    pass
    return class_map

def map_label_to_fqn(label, class_map):
    label = label.replace('"', '').strip()
    if not label or "-res" in label.lower():
        return None
    if "." in label:
        return label
    if label in class_map and len(class_map[label]) == 1:
        return list(class_map[label])[0]
    if "$" in label:
        outer = label.split("$")[0]
        if outer in class_map and len(class_map[outer]) == 1:
            return f"{list(class_map[outer])[0]}{label[len(outer):]}"
    if label in class_map:
        candidates = sorted(list(class_map[label]))
        prod = [c for c in candidates if "test" not in c.lower()]
        return prod[0] if prod else candidates[0]
    return label

def parse_cma_output(cma_json_path, output_json_path, dataset_path=None):
    """
    Parses CMA-format cluster output from Triplet-Guided CHGNN into standardized output.json.
    Filters out resource nodes and maps simple class names to canonical FQNs.
    """
    if not os.path.exists(cma_json_path):
        write_error(output_json_path, f"CMA output file not found at {cma_json_path}")

    with open(cma_json_path, 'r', encoding='utf-8') as f:
        cma_data = json.load(f)

    nodes = cma_data.get("nodes", [])
    clusters = cma_data.get("clusters", [])

    id_to_label = {str(n["id"]): str(n["label"]) for n in nodes if "id" in n and "label" in n}
    class_map = build_class_lookup(dataset_path) if dataset_path else {}

    microservices = {}
    valid_idx = 1
    for cluster in clusters:
        node_ids = cluster.get("nodes", [])
        classes = []
        for nid in node_ids:
            raw_label = id_to_label.get(str(nid), str(nid))
            canonical = map_label_to_fqn(raw_label, class_map)
            if canonical:
                classes.append(canonical)

        if classes:
            cluster_key = f"microservice_{valid_idx}"
            microservices[cluster_key] = sorted(list(set(classes)))
            valid_idx += 1

    os.makedirs(os.path.dirname(output_json_path) or '.', exist_ok=True)
    out_payload = {
        "tool": "TripletGuidedCHGNN",
        "microservices": microservices
    }

    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(out_payload, f, indent=4)

    print(f"Standardized decomposition written to {output_json_path} ({len(microservices)} microservices)")

def resolve_dataset_info(dataset_path, root_dir):
    """
    Derives dataset name and resolves monolith codebase path without hardcoded mappings.
    """
    dataset_path = os.path.abspath(dataset_path)
    dataset_name = os.path.basename(os.path.normpath(dataset_path))

    dataset_json = os.path.join(dataset_path, "dataset.json")
    monolith_path = None
    if os.path.exists(dataset_json):
        try:
            with open(dataset_json, 'r', encoding='utf-8') as f:
                d = json.load(f)
                src = d.get("source_path")
                if src:
                    cand1 = os.path.abspath(os.path.join(dataset_path, src))
                    cand2 = os.path.abspath(os.path.join(root_dir, src))
                    if os.path.exists(cand1):
                        monolith_path = cand1
                    elif os.path.exists(cand2):
                        monolith_path = cand2
        except Exception as e:
            print(f"Warning: Could not read source_path from {dataset_json}: {e}")

    if not monolith_path:
        # Scan dataset_path for subdirectories with compiled classes or Java sources
        for r, dirs, _ in os.walk(dataset_path):
            if "target" in dirs or "build" in dirs or "src" in dirs:
                monolith_path = r
                break
        if not monolith_path:
            monolith_path = dataset_path

    return dataset_name, monolith_path

def resolve_data_folder(repo_dir, dataset_name, model, force_recompute=False):
    """
    Locates the CHGNN data folder under data_layer/utilities/data/.
    Uses dedicated '{dataset_name}_{model}'.
    If force_recompute is True, unlinks symlinks or clears existing data folder so it gets rebuilt.
    """
    data_base = os.path.join(repo_dir, "data_layer/utilities/data")
    target_name = f"{dataset_name}_{model}"
    target_path = os.path.join(data_base, target_name)

    if force_recompute:
        if os.path.islink(target_path):
            os.unlink(target_path)
            print(f"Removed cached symlink: {target_path}")
        elif os.path.exists(target_path):
            shutil.rmtree(target_path, ignore_errors=True)
            print(f"Cleared existing data directory: {target_path}")
        return target_path, dataset_name

    return target_path, dataset_name

def run_cmd(cmd, cwd, root_dir, docker_image=None):
    if docker_image:
        docker_cmd = [
            "docker", "run", "--rm",
            "--network", "host",
            "-v", f"{root_dir}:{root_dir}",
            "-w", cwd,
            docker_image
        ] + cmd
        return subprocess.run(docker_cmd)
    else:
        return subprocess.run(cmd, cwd=cwd)

def build_chgnn_data(dataset_path, data_folder, num_clusters=None):
    """
    Constructs recommended heterogeneous graph representation anew
    directly from source code and dataset.json using generate_chgnn_graph.
    """
    print(f"\n{'='*60}")
    print(f"Constructing Recommended CHGNN graph data for {os.path.basename(dataset_path)}")
    print(f"Dataset path: {dataset_path}")
    print(f"Target folder: {data_folder}")
    print(f"{'='*60}\n")
    generate_chgnn_graph(dataset_path=dataset_path, output_data_dir=data_folder, num_clusters=num_clusters)

def run_decomposition(dataset_path, output_path=None, model="AE_EGCN_Separate", code="with_edge_loss",
                      epochs=100, alpha=0.7, triplet_num=100, parse_only=False, python_bin=None,
                      docker_image=None, force_recompute=False):
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    tool_dir = os.path.join(root_dir, "tools/triplet-guided-chgnn")
    repo_dir = os.path.join(tool_dir, "triplet-guided-chgnn")

    dataset_name, monolith_path = resolve_dataset_info(dataset_path, root_dir)

    if not output_path:
        output_path = os.path.join(tool_dir, "outputs", dataset_name)
    os.makedirs(output_path, exist_ok=True)
    output_json_path = os.path.join(output_path, "output.json")

    data_folder, chgnn_key = resolve_data_folder(repo_dir, dataset_name, model, force_recompute=force_recompute)
    triplebound_results_dir = os.path.join(data_folder, "triplebound_results")

    # If parse-only is requested
    if parse_only:
        print(f"Parse-only mode requested for {dataset_name}...")
        candidates = glob.glob(os.path.join(output_path, "*cma_format*.json")) + \
                     glob.glob(os.path.join(triplebound_results_dir, "**/*cma_format*.json"), recursive=True) + \
                     glob.glob(os.path.join(triplebound_results_dir, "*cma_format*.json"))
        if not candidates:
            write_error(output_json_path, f"No CMA-format cluster output found in {output_path} or {triplebound_results_dir}")
        latest_cma = max(candidates, key=os.path.getmtime)
        print(f"Found CMA cluster output: {latest_cma}")
        parse_cma_output(latest_cma, output_json_path, dataset_path=dataset_path)
        return

    # Check if CHGNN data directory exists and has ICU; if not or if forced, build dynamically from source
    icu_path = os.path.join(data_folder, "temp", "inter_class_usage.json")
    if not os.path.exists(icu_path) or force_recompute:
        print(f"Data folder or ICU file not found in {data_folder} or force_recompute=True. Generating recommended graph...")
        build_chgnn_data(dataset_path=dataset_path, data_folder=data_folder)
    else:
        print(f"Using prepared CHGNN data in {data_folder}...")

    py_bin = python_bin if python_bin else ("python3" if docker_image else sys.executable)
    run_script = os.path.join(repo_dir, "scripts/run_triplebound_pipeline.py")
    cmd = [
        py_bin,
        run_script,
        "--data", chgnn_key,
        "--model", model,
        "--code", code,
        "--attempt", "1",
        "--epochs", str(epochs),
        "--alpha", str(alpha),
        "--triplet-num", str(triplet_num)
    ]

    print("\nExecuting Triplet-Guided CHGNN training pipeline:")
    print(" ".join(cmd))

    proc = run_cmd(cmd, cwd=repo_dir, root_dir=root_dir, docker_image=docker_image)
    if proc.returncode != 0:
        write_error(output_json_path, f"Triplet-Guided CHGNN failed with exit code {proc.returncode}")

    # Locate generated CMA file and convert
    candidates = glob.glob(os.path.join(triplebound_results_dir, "**/*cma_format*.json"), recursive=True) + \
                 glob.glob(os.path.join(triplebound_results_dir, "*cma_format*.json"))
    if not candidates:
        write_error(output_json_path, f"Training succeeded but no CMA output found in {triplebound_results_dir}")

    latest_cma = max(candidates, key=os.path.getmtime)
    print(f"Converting latest CMA output: {latest_cma} -> {output_json_path}")
    parse_cma_output(latest_cma, output_json_path, dataset_path=dataset_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Triplet-Guided CHGNN Tool Runner")
    parser.add_argument("--dataset-path", "-d", type=str, required=True, help="Path to dataset directory")
    parser.add_argument("--output-path", "-o", type=str, help="Path to output directory")
    parser.add_argument("--model", type=str, default="AE_EGCN_Separate", help="CHGNN Model variant")
    parser.add_argument("--code", type=str, default="with_edge_loss", choices=["with_edge_loss", "without_edge_loss"])
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs")
    parser.add_argument("--alpha", type=float, default=0.7, help="Triplet loss weight")
    parser.add_argument("--triplet-num", type=int, default=100, help="Number of triplets")
    parser.add_argument("--force-recompute", "--recompute-graph", action="store_true",
                        help="Recompute graph representation directly from source code, ignoring any cached graphs")
    parser.add_argument("--parse-only", action="store_true", help="Parse existing CMA output into output.json without training")
    parser.add_argument("--python-bin", type=str, help="Path to Python executable in CHGNN environment")
    parser.add_argument("--docker-image", type=str, help="Docker image name to run inside container")
    args = parser.parse_args()

    run_decomposition(
        dataset_path=args.dataset_path,
        output_path=args.output_path,
        model=args.model,
        code=args.code,
        epochs=args.epochs,
        alpha=args.alpha,
        triplet_num=args.triplet_num,
        parse_only=args.parse_only,
        python_bin=args.python_bin,
        docker_image=args.docker_image,
        force_recompute=args.force_recompute
    )
