# /// script
# requires-python = ">=3.9"
# ///

import os
import json
import argparse

def generate_universal_json(source_dir, output_file):
    """
    Generates the Universal JSON representation.
    Note: CICS Genapp is a COBOL application, so we do not extract Java methods.
    """
    print(f"Skipping AST parsing: {source_dir} is a COBOL application.")
    
    output_data = {
        "dataset": "CICS Genapp",
        "source_path": os.path.relpath(source_dir)
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=4)
    
    print(f"Universal JSON saved to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dataset: Monolith Adapter for CICS Genapp")
    parser.add_argument("--source_dir", type=str, default="cics-genapp", help="Path to the monolithic source code")
    parser.add_argument("--output", type=str, default="dataset.json", help="Output path for the Universal JSON")
    
    args = parser.parse_args()
    generate_universal_json(args.source_dir, args.output)
