# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import json
import argparse

def create_magnet_config(dataset_dir, output_config):
    """
    Validates that the dataset has the required raw files for MAGNET (Java source + XMI)
    and generates a config for the Tool Wrapper to mount/pass into Docker.
    """
    xmi_path = None
    source_dir = None
    
    for root, dirs, files in os.walk(dataset_dir):
        for file in files:
            if file.endswith('.xmi'):
                xmi_path = os.path.abspath(os.path.join(root, file))
        # Find the first directory that looks like the root of the source code 
        # (e.g. contains build.gradle or pom.xml)
        if source_dir is None and ('build.gradle' in files or 'pom.xml' in files):
            source_dir = os.path.abspath(root)
            
    if not source_dir:
        # Fallback to the dataset dir itself
        source_dir = os.path.abspath(dataset_dir)
        
    if not xmi_path:
        print(f"WARNING: No .xmi file found in {dataset_dir}. MAGNET strictly requires a KDM XMI file.")
        xmi_path = os.path.abspath(os.path.join(dataset_dir, "missing_kdm.xmi"))
        
    config = {
        "system_code_path": source_dir,
        "kdm_file_path": xmi_path,
        "system_path": os.path.abspath(os.path.join(dataset_dir, "magnet_output"))
    }
    
    os.makedirs(os.path.dirname(output_config) or '.', exist_ok=True)
    with open(output_config, 'w') as f:
        json.dump(config, f, indent=4)
        
    print(f"Generated MAGNET config: {output_config}")
    print(json.dumps(config, indent=2))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool: Monolith Converter for MAGNET")
    parser.add_argument("--dataset_dir", type=str, required=True, help="Path to the monolithic dataset directory")
    parser.add_argument("--output", type=str, required=True, help="Path to save magnet_config.json")
    args = parser.parse_args()
    create_magnet_config(args.dataset_dir, args.output)
