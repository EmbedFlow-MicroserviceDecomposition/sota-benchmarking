# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import subprocess
import sys

def run_setup():
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    cli_dir = os.path.join(tool_dir, "Mono2Micro-CLI")
    
    if not os.path.exists(cli_dir):
        print(f"Error: {cli_dir} does not exist.")
        print("Please download and extract the IBM Mono2Micro CLI into tools/mono2micro/Mono2Micro-CLI")
        sys.exit(1)
        
    mono2micro_bin = os.path.join(cli_dir, "mono2micro")
    if not os.path.exists(mono2micro_bin):
        print(f"Error: {mono2micro_bin} executable not found.")
        sys.exit(1)
        
    print("Running mono2micro install -c=docker...")
    try:
        subprocess.run(["./mono2micro", "install", "-c=docker"], cwd=cli_dir, check=True)
        print("Setup completed successfully.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to install mono2micro dependencies: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_setup()
