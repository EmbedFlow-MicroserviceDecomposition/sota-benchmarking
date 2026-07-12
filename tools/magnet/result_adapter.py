# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import csv
import json
import argparse
import os

def parse_magnet_output(magnet_csv_path, output_json_path):
    """
    Parses MAGNET's _bestCLuster.csv into the standard Processed Result JSON.
    """
    if not os.path.exists(magnet_csv_path):
        print(f"Error: Could not find MAGNET output at {magnet_csv_path}")
        return

    clusters = {}
    with open(magnet_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for idx, row in enumerate(reader):
            if not row:
                continue
            # Each row is a list of method names for one microservice
            cluster_id = f"microservice_{idx+1}"
            clusters[cluster_id] = row
            
    processed_result = {
        "tool": "MAGNET",
        "microservices": clusters
    }
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_json_path) or '.', exist_ok=True)
    
    with open(output_json_path, 'w', encoding='utf-8') as f:
        json.dump(processed_result, f, indent=4)
        
    print(f"Standardized {len(clusters)} microservices to {output_json_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tool: Result Adapter for MAGNET")
    parser.add_argument("--input", type=str, required=True, help="Path to MAGNET's _bestCLuster.csv")
    parser.add_argument("--output", type=str, required=True, help="Path to save processed_result.json")
    args = parser.parse_args()
    parse_magnet_output(args.input, args.output)
