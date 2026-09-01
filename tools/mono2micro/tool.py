# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import json
import argparse
import subprocess
import sys

def write_error(output_json_path, message):
    os.makedirs(os.path.dirname(output_json_path) or '.', exist_ok=True)
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump({"error": message, "tool": "Mono2Micro"}, f, indent=4)
    print(f"Error written to {output_json_path}: {message}")
    sys.exit(1)

def get_dataset_files(dataset_path, output_json_path):
    dataset_json_path = os.path.join(dataset_path, "dataset.json")
    if not os.path.exists(dataset_json_path):
        write_error(output_json_path, f"dataset.json not found in {dataset_path}")

    with open(dataset_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    source_path = data.get("source_path")
    if not source_path:
        write_error(output_json_path, "source_path missing in dataset.json")

    abs_source = os.path.abspath(os.path.join(dataset_path, source_path))
    if not os.path.exists(abs_source):
        write_error(output_json_path, f"Source path does not exist: {abs_source}")
        
    return abs_source

def parse_mono2micro_output(oriole_json_path, dataset_json_path, output_json_path):
    if not os.path.exists(oriole_json_path):
        print(f"Error: Could not find Mono2Micro output at {oriole_json_path}")
        return

    with open(oriole_json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Load dataset.json to map FQCN to methods
    class_to_methods = {}
    if os.path.exists(dataset_json_path):
        with open(dataset_json_path, 'r', encoding='utf-8') as f:
            dataset_data = json.load(f)
            methods_dict = dataset_data.get("methods", {})
            for method_id, m_data in methods_dict.items():
                package_name = m_data.get("package", "")
                c_name = m_data.get("class", "")
                fqcn = f"{package_name}.{c_name}" if package_name else c_name
                
                if fqcn not in class_to_methods:
                    class_to_methods[fqcn] = []
                class_to_methods[fqcn].append(method_id)

    # Prefer the business logic partition (generated when logs are present)
    # Fallback to static analysis partition or mono_run_time_call_graph
    graph = data.get("micro_detail_partition_by_business_logic")
    if not graph:
        graph = data.get("micro_detail_partition_by_static_analysis")
    if not graph:
        graph = data.get("mono_run_time_call_graph", {})
        
    nodes = graph.get("nodes", [])
    
    clusters = {}
    for node in nodes:
        class_name = node.get("name")
        group_id = node.get("group")
        
        if class_name and group_id is not None:
            fqcn = node.get("FQCN")
            if not fqcn:
                fqcn = class_name
                
            cluster_name = f"microservice_{group_id}"
            if cluster_name not in clusters:
                clusters[cluster_name] = []
                
            # Expand class to its methods for standard SOTA evaluation
            methods = class_to_methods.get(fqcn, [])
            if methods:
                clusters[cluster_name].extend(methods)
            else:
                clusters[cluster_name].append(fqcn)
            
    processed_result = {
        "tool": "Mono2Micro",
        "microservices": clusters
    }
    
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(processed_result, f, indent=4)
        
    print(f"Standardized {len(clusters)} microservices to {output_json_path}")

def run_mono2micro(dataset_path, output_path):
    os.makedirs(output_path, exist_ok=True)
    json_out = os.path.join(output_path, "output.json")
    
    source_dir = get_dataset_files(dataset_path, json_out)
    
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    cli_dir = os.path.join(tool_dir, "Mono2Micro-CLI")
    mono2micro_bin = os.path.join(cli_dir, "mono2micro")
    
    if not os.path.exists(mono2micro_bin):
        write_error(json_out, "mono2micro binary not found. Please follow README instructions.")

    abs_output = os.path.abspath(output_path)
    tables_dir = os.path.join(abs_output, "tables")
    
    # 1. Run Analyze
    print(f"Running mono2micro analyze on {source_dir}...")
    analyze_cmd = [
        "sh", "./mono2micro", "analyze",
        "-s", source_dir,
        "-o", tables_dir
    ]
    try:
        subprocess.run(analyze_cmd, cwd=cli_dir, check=True)
    except subprocess.CalledProcessError as e:
        write_error(json_out, f"Analyze step failed: {e}")
        
    # 2. Print instructions for instrumentation and runtime traces
    logs_dir = os.path.join(abs_output, "logs")
    contexts_dir = os.path.join(abs_output, "contexts")
    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(contexts_dir, exist_ok=True)
    
    agent_jar = os.path.join(cli_dir, "instrumenter", "minerva-agent-1.0.jar")
    
    print("\n" + "="*80)
    print("ACTION REQUIRED: RUNTIME DATA COLLECTION")
    print("="*80)
    print("Mono2Micro requires dynamic traces. Please open a new terminal and run the instrumented monolith.")
    
    print(f"\n1. Attach the Minerva agent to your application JVM (via JAVA_OPTS, JVM_ARGS, or direct argument):")
    print(f"   -javaagent:{agent_jar}={tables_dir}")
    print(f"\n2. Pipe or save your application's intercepted runtime traces (stderr/stdout logs) to:")
    print(f"   {logs_dir}/console.log")
    
    print("\nPlease follow the build, deployment, and execution instructions specified in the dataset's README.md.")
    
    print("\nOnce the application is running, run the following command in another terminal to start recording traces:")
    print(f"\n3. Command (Record Use Cases):")
    print(f"   {mono2micro_bin} usecase -o {contexts_dir}/usecases.json")
    print("\nFollow the interactive instructions to execute and record your business use cases.")
    print("="*80 + "\n")
    
    # 3. Wait for User
    input("Press Enter when you have finished recording use cases and usecases.json is generated...")

    # 4. Run Recommend
    print("\nRunning mono2micro recommend...")
    recommend_cmd = [
        "sh", "./mono2micro", "recommend",
        "-d", abs_output
    ]
    try:
        subprocess.run(recommend_cmd, cwd=cli_dir, check=True)
    except subprocess.CalledProcessError as e:
        write_error(json_out, f"Recommend step failed: {e}")
        
    # 5. Parse Output
    oriole_json = os.path.join(abs_output, "mono2micro", "mono2micro-output", "oriole", "final_graph.json")
    dataset_json_path = os.path.join(dataset_path, "dataset.json")
    print("\nParsing Mono2Micro AI output...")
    parse_mono2micro_output(oriole_json, dataset_json_path, json_out)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool orchestrator for Mono2Micro")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to the dataset directory")
    parser.add_argument("--output-path", type=str, required=True, help="Path to the tool output directory")
    
    args = parser.parse_args()
    run_mono2micro(args.dataset_path, args.output_path)
