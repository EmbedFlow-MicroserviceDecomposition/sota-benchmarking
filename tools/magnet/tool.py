# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import json
import csv
import argparse
import subprocess
import sys

def write_error(output_json_path, message):
    os.makedirs(os.path.dirname(output_json_path) or '.', exist_ok=True)
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump({"error": message, "tool": "MAGNET"}, f, indent=4)
    print(f"Error written to {output_json_path}: {message}")
    sys.exit(1)

def get_dataset_files(dataset_path, output_json_path):
    dataset_json_path = os.path.join(dataset_path, "dataset.json")
    if not os.path.exists(dataset_json_path):
        write_error(output_json_path, f"dataset.json not found in {dataset_path}")

    with open(dataset_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    source_path = data.get("source_path")
    xmi_path = data.get("xmi_path")

    if not source_path:
        write_error(output_json_path, "source_path missing in dataset.json")
    if not xmi_path:
        write_error(output_json_path, "xmi_path missing in dataset.json (MAGNET requires a KDM XMI file)")

    # Resolve paths relative to the dataset_path
    abs_source = os.path.abspath(os.path.join(dataset_path, source_path))
    abs_xmi = os.path.abspath(os.path.join(dataset_path, xmi_path))

    if not os.path.exists(abs_source):
        write_error(output_json_path, f"Source path does not exist: {abs_source}")
    if not os.path.exists(abs_xmi):
        write_error(output_json_path, f"XMI file does not exist: {abs_xmi}")

    return abs_xmi, abs_source

def parse_magnet_output(magnet_csv_path, output_json_path):
    if not os.path.exists(magnet_csv_path):
        print(f"Error: Could not find MAGNET output at {magnet_csv_path}")
        return

    clusters = {}
    with open(magnet_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for idx, row in enumerate(reader):
            if not row:
                continue
            cluster_id = f"microservice_{idx+1}"
            clusters[cluster_id] = row
            
    processed_result = {
        "tool": "MAGNET",
        "microservices": clusters
    }
    
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(processed_result, f, indent=4)
        
    print(f"Standardized {len(clusters)} microservices to {output_json_path}")

def run_magnet(dataset_path, output_path):
    os.makedirs(output_path, exist_ok=True)
    json_out = os.path.join(output_path, "output.json")
    
    xmi_path, source_dir = get_dataset_files(dataset_path, json_out)
    
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Build the Docker image
    print("Building MAGNET Docker image...")
    subprocess.run(["docker", "build", "-t", "fyp-magnet", tool_dir], check=True)
    
    # 2. Run the Docker container
    print("Running MAGNET...")
    
    # We map the host paths to container paths
    # /dataset -> dataset_path
    # /output -> output_path
    # We need to find the relative paths of xmi and source within the dataset_path
    
    xmi_rel = os.path.relpath(xmi_path, dataset_path)
    source_rel = os.path.relpath(source_dir, dataset_path)
    
    container_xmi = f"/dataset/{xmi_rel}"
    container_source = f"/dataset/{source_rel}"
    
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{os.path.abspath(dataset_path)}:/dataset:ro",
        "-v", f"{os.path.abspath(output_path)}:/output:rw",
        "fyp-magnet",
        "python", "train.py",
        "--system_path=/output",
        f"--kdm_file_path={container_xmi}",
        f"--system_code_path={container_source}"
    ]
    
    subprocess.run(cmd, check=True)
    
    # 3. Parse the output
    csv_out = os.path.join(output_path, "_bestCLuster.csv")
    json_out = os.path.join(output_path, "output.json")
    print("Parsing MAGNET output...")
    parse_magnet_output(csv_out, json_out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool orchestrator for MAGNET")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to the dataset directory")
    parser.add_argument("--output-path", type=str, required=True, help="Path to the tool output directory")
    
    args = parser.parse_args()
    run_magnet(args.dataset_path, args.output_path)
