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

def write_error(output_json_path, message):
    os.makedirs(os.path.dirname(output_json_path) or '.', exist_ok=True)
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump({"error": message, "tool": "TripletGuidedCHGNN"}, f, indent=4)
    print(f"Error written to {output_json_path}: {message}")
    sys.exit(1)

def parse_cma_output(cma_json_path, output_json_path):
    """
    Parses CMA-format cluster output from Triplet-Guided CHGNN into standardized output.json.
    """
    if not os.path.exists(cma_json_path):
        write_error(output_json_path, f"CMA output file not found at {cma_json_path}")

    with open(cma_json_path, 'r', encoding='utf-8') as f:
        cma_data = json.load(f)

    nodes = cma_data.get("nodes", [])
    clusters = cma_data.get("clusters", [])

    id_to_label = {str(n["id"]): str(n["label"]) for n in nodes if "id" in n and "label" in n}

    microservices = {}
    for idx, cluster in enumerate(clusters):
        cluster_label = cluster.get("label", f"microservice_{idx+1}")
        cluster_key = f"microservice_{idx+1}" if not cluster_label.startswith("microservice_") else cluster_label

        node_ids = cluster.get("nodes", [])
        classes = []
        for nid in node_ids:
            label = id_to_label.get(str(nid), str(nid))
            classes.append(label)

        if classes:
            microservices[cluster_key] = sorted(classes)

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
    Checks direct match '{dataset_name}_{model}'.
    If absent, checks for legacy/author cached directory (e.g. acme_..., dayTrader_..., pbw_...)
    and automatically symlinks it so dataset_name works directly.
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

    if os.path.exists(target_path):
        return target_path, dataset_name

    # Check for normalized match among existing author folders
    clean_target = dataset_name.lower().replace("-", "").replace("_", "")
    if os.path.exists(data_base):
        for entry in os.listdir(data_base):
            if not entry.endswith(f"_{model}"):
                continue
            prefix = entry[:-len(f"_{model}")]
            clean_prefix = prefix.lower().replace("-", "").replace("_", "").replace("sample.", "")
            if clean_target == clean_prefix or clean_target in clean_prefix or clean_prefix in clean_target:
                matched_folder = os.path.join(data_base, entry)
                try:
                    os.symlink(entry, target_path)
                    print(f"Linked author-cached folder {entry} -> {target_name}")
                    return target_path, dataset_name
                except Exception:
                    return matched_folder, prefix

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

def build_chgnn_data_from_monolith(repo_dir, root_dir, dataset_name, monolith_path, data_folder,
                                   model="AE_EGCN_Separate", triplet_num=100, python_bin=None,
                                   docker_image=None):
    """
    Runs parser pipeline (parser/main.py --to-chgnn and generate_servlet_services.py)
    to dynamically construct all required CHGNN input data for an arbitrary dataset.
    """
    print(f"\n{'='*60}")
    print(f"Constructing CHGNN graph data for {dataset_name}")
    print(f"Source: {monolith_path}")
    print(f"Target: {data_folder}")
    print(f"{'='*60}\n")

    parser_dir = os.path.join(repo_dir, "parser")
    temp_convert_dir = os.path.join(data_folder, "_convert_tmp")
    os.makedirs(temp_convert_dir, exist_ok=True)
    vertices_file = os.path.join(temp_convert_dir, "vertices.json")

    py_bin = python_bin if python_bin else ("python3" if docker_image else sys.executable)

    # Step 1: Run parser/main.py with --to-chgnn --improved-converter
    cmd1 = [
        py_bin,
        os.path.join(parser_dir, "main.py"),
        monolith_path,
        "--out", vertices_file,
        "--repo-name", dataset_name,
        "--multi-service",
        "--generate-triplets",
        "--num-triplets", str(triplet_num),
        "--to-chgnn",
        "--improved-converter",
        "--chgnn-output-dir", temp_convert_dir
    ]
    print("Executing parser pipeline (Step 1/2):")
    print(" ".join(cmd1))
    proc = run_cmd(cmd1, cwd=parser_dir, root_dir=root_dir, docker_image=docker_image)
    if proc.returncode != 0:
        raise RuntimeError(f"Parser failed with exit code {proc.returncode}")

    if not os.path.exists(vertices_file):
        raise RuntimeError(f"Parser succeeded but vertices.json not found at {vertices_file}")

    # Step 2: Run parser/generate_servlet_services.py
    service_triplets_file = os.path.join(temp_convert_dir, "service_triplets.json")
    cmd2 = [
        py_bin,
        os.path.join(parser_dir, "generate_servlet_services.py"),
        "--input", vertices_file,
        "--output", service_triplets_file
    ]
    print("\nGenerating service triplets (Step 2/2):")
    print(" ".join(cmd2))
    proc = run_cmd(cmd2, cwd=parser_dir, root_dir=root_dir, docker_image=docker_image)
    if proc.returncode != 0:
        raise RuntimeError(f"generate_servlet_services failed with exit code {proc.returncode}")

    # Step 3: Organize into standard CHGNN directory layout (temp/ and custom/)
    temp_dir = os.path.join(data_folder, "temp")
    custom_dir = os.path.join(data_folder, "custom")
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(custom_dir, exist_ok=True)

    temp_files = [
        "inter_class_usage.json", "callgraph.dot", "service.json",
        "db.json", "content.csv", "struct.csv", "service_triplets.json"
    ]
    for fname in temp_files:
        src = os.path.join(temp_convert_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(temp_dir, fname))

    custom_files = [
        "gcnconfig_with_edge_loss.json", "gcnconfig_without_edge_loss.json", "seeds.txt"
    ]
    for fname in custom_files:
        src = os.path.join(temp_convert_dir, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(custom_dir, fname))

    ignore_file = os.path.join(custom_dir, "ignore_classes.txt")
    if not os.path.exists(ignore_file):
        open(ignore_file, 'w').close()

    shutil.rmtree(temp_convert_dir, ignore_errors=True)
    print(f"\nCHGNN data folder successfully prepared at: {data_folder}\n")

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
        parse_cma_output(latest_cma, output_json_path)
        return

    # Check if CHGNN data directory exists; if not or if forced, build dynamically from source monolith
    if not os.path.exists(data_folder) or force_recompute:
        print(f"Data folder {data_folder} not found or force_recompute=True. Running parser pipeline on {monolith_path}...")
        build_chgnn_data_from_monolith(
            repo_dir=repo_dir,
            root_dir=root_dir,
            dataset_name=dataset_name,
            monolith_path=monolith_path,
            data_folder=data_folder,
            model=model,
            triplet_num=triplet_num,
            python_bin=python_bin,
            docker_image=docker_image
        )
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
    parse_cma_output(latest_cma, output_json_path)

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
