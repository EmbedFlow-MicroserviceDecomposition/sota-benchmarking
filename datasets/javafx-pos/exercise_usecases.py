import os
import sys
import argparse
import subprocess

CONTAINER_NAME = None

USECASES = [
    "Login",
    "ManageCategory",
    "ManageProduct",
    "ManageSupplier",
    "ManageEmployee",
    "CreateSale",
    "CreatePurchase",
    "GenerateInvoice"
]

def run_usecase(name, agent_args=None, log_file=None, **kwargs):
    print(f"--- Executing Java application for usecase: {name} ---")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    jar_path = os.path.join(current_dir, "JavaFX-Point-of-Sales/target/inventory-1.0.jar")
    if not os.path.exists(jar_path):
        raise FileNotFoundError(f"Application JAR not found at {jar_path}. Please build it first.")

    cmd = ["java"]
    if agent_args:
        cmd.append(agent_args)
    cmd.extend([
        "-cp", jar_path,
        "com.rafsan.inventory.UseCaseRunner",
        name
    ])

    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            res = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
    else:
        res = subprocess.run(cmd)

    print(f"Java execution for {name} -> exit code {res.returncode}")

def run_all(agent_args=None, log_file=None):
    for uc in USECASES:
        run_usecase(uc, agent_args=agent_args, log_file=log_file)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Exercise use cases for JavaFX POS")
    parser.add_argument("--usecase", type=str, help="Specific usecase to run")
    parser.add_argument("--list", action="store_true", help="List available usecases")
    parser.add_argument("--agent-args", type=str, help="JVM agent arguments (e.g. -javaagent:...)")
    parser.add_argument("--log-file", type=str, help="Log file path to append execution traces")
    args = parser.parse_args()

    if args.list:
        print("\n".join(USECASES))
    elif args.usecase:
        run_usecase(args.usecase, agent_args=args.agent_args, log_file=args.log_file)
    else:
        run_all(agent_args=args.agent_args, log_file=args.log_file)
