import os
import sys
import time
import argparse
import subprocess
import importlib.util

def load_workload_module(dataset_path):
    workload_file = os.path.join(dataset_path, "exercise_usecases.py")
    if not os.path.exists(workload_file):
        raise FileNotFoundError(
            f"Workload driver '{workload_file}' not found for dataset at '{dataset_path}'. "
            f"Each dataset must provide 'exercise_usecases.py' defining USECASES and run_usecase(name)."
        )

    spec = importlib.util.spec_from_file_location("exercise_usecases", workload_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def record_usecases(dataset_path, output_path=None, container_name=None, agent_jar=None):
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
    dataset_path = os.path.abspath(dataset_path)
    dataset_name = os.path.basename(dataset_path)

    if not output_path:
        output_path = os.path.join(root_dir, "tools/mono2micro/outputs", dataset_name)
    output_path = os.path.abspath(output_path)

    cli_dir = os.path.join(root_dir, "tools/mono2micro/Mono2Micro-CLI")
    mono2micro_bin = os.path.join(cli_dir, "mono2micro")
    if not os.path.exists(mono2micro_bin):
        raise FileNotFoundError(f"mono2micro CLI not found at '{mono2micro_bin}'.")

    if not agent_jar:
        agent_jar = os.path.join(cli_dir, "instrumenter/minerva-agent-1.0.jar")

    tables_dir = os.path.join(output_path, "tables")
    logs_dir = os.path.join(output_path, "logs")
    contexts_dir = os.path.join(output_path, "contexts")
    log_file = os.path.join(logs_dir, "console.log")

    os.makedirs(logs_dir, exist_ok=True)
    os.makedirs(contexts_dir, exist_ok=True)
    os.makedirs(tables_dir, exist_ok=True)

    module = load_workload_module(dataset_path)
    usecases = getattr(module, "USECASES", [])
    if not usecases:
        raise ValueError(f"No USECASES list defined in {dataset_path}/exercise_usecases.py")

    target_container = container_name or getattr(module, "CONTAINER_NAME", None)

    # If standalone execution, clear previous log file
    if not target_container and os.path.exists(log_file):
        os.remove(log_file)

    output_context_json = os.path.join(contexts_dir, "usecases.json")
    print(f"Starting Mono2Micro usecase recording for '{dataset_name}'...")
    print(f"Contexts file: {output_context_json}")
    print(f"Log file: {log_file}")
    if target_container:
        print(f"Docker container: {target_container}")

    cmd = ["sh", "./mono2micro", "usecase", "-o", output_context_json]
    proc = subprocess.Popen(
        cmd,
        cwd=cli_dir,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    time.sleep(2)

    for uc in usecases:
        print(f"\n==========================================")
        print(f"Recording Usecase: {uc}")
        print(f"==========================================")
        proc.stdin.write(f"{uc}\n")
        proc.stdin.flush()
        time.sleep(1)

        module.run_usecase(
            uc,
            agent_args=f"-javaagent:{agent_jar}={tables_dir}",
            log_file=log_file,
            tables_dir=tables_dir
        )
        time.sleep(1)

        proc.stdin.write("9\n")
        proc.stdin.flush()
        time.sleep(1)

    print("\nExiting usecase recording...")
    proc.stdin.write("1\n")
    proc.stdin.flush()

    out, _ = proc.communicate(timeout=20)
    print("Mono2Micro Output:\n", out)

    if target_container:
        print(f"Dumping logs from container '{target_container}' to {log_file}...")
        with open(log_file, "w", encoding="utf-8") as f:
            subprocess.run(["docker", "logs", target_container], stdout=f, stderr=subprocess.STDOUT)

    print(f"Dynamic trace recording for '{dataset_name}' completed successfully.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generic Mono2Micro Dynamic Trace Recorder")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to dataset directory")
    parser.add_argument("--output-path", type=str, help="Path to output directory (default: tools/mono2micro/outputs/<dataset>)")
    parser.add_argument("--container", type=str, help="Docker container name to dump logs from (optional)")
    parser.add_argument("--agent-jar", type=str, help="Path to minerva-agent-1.0.jar (optional)")
    args = parser.parse_args()

    record_usecases(
        dataset_path=args.dataset_path,
        output_path=args.output_path,
        container_name=args.container,
        agent_jar=args.agent_jar
    )
