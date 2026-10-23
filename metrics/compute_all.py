# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import os
import json
import argparse
import sys
from partition import PartitionError, load_dataset, load_partition
from chm.metric import evaluate_chm
from chd.metric import evaluate_chd
from sm.metric import evaluate_sm
from icp.metric import evaluate_icp
from ifn.metric import evaluate_ifn
from ned.metric import evaluate_ned
from bcp.metric import evaluate_bcp

class MetricsIncomplete(Exception):
    """At least one metric raised; the scores that could be computed were still written."""


def compute_all_metrics(dataset_path, output_path, ned_lo=5, ned_hi=20, eps=0.5):
    """
    Computes all microservice evaluation metrics (CHM, CHD, SM, ICP, IFN, NED, BCP)
    for a given dataset and tool output directory.
    """
    results = {}
    errors = {}

    # fail loudly on an error/unreadable output.json instead of scoring it
    load_partition(output_path, load_dataset(dataset_path))

    print("=== Computing All Evaluation Metrics ===")

    try:
        results["CHM"] = evaluate_chm(dataset_path, output_path)
    except Exception as e:
        errors["CHM"] = str(e)
        print(f"Error computing CHM: {e}")

    try:
        results["CHD"] = evaluate_chd(dataset_path, output_path)
    except Exception as e:
        errors["CHD"] = str(e)
        print(f"Error computing CHD: {e}")

    try:
        results["SM"] = evaluate_sm(dataset_path, output_path)
    except Exception as e:
        errors["SM"] = str(e)
        print(f"Error computing SM: {e}")

    try:
        results["ICP"] = evaluate_icp(dataset_path, output_path)
    except Exception as e:
        errors["ICP"] = str(e)
        print(f"Error computing ICP: {e}")

    try:
        results["IFN"] = evaluate_ifn(dataset_path, output_path)
    except Exception as e:
        errors["IFN"] = str(e)
        print(f"Error computing IFN: {e}")

    try:
        results["NED"] = evaluate_ned(dataset_path, output_path, lo=ned_lo, hi=ned_hi, eps=eps)
    except Exception as e:
        errors["NED"] = str(e)
        print(f"Error computing NED: {e}")

    try:
        results["BCP"] = evaluate_bcp(dataset_path, output_path)
    except Exception as e:
        errors["BCP"] = str(e)
        print(f"Error computing BCP: {e}")

    summary_file = os.path.join(output_path, "metrics_summary.json")
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    print(f"\n========================================")
    print(f"Metrics calculation complete!")
    print(f"Summary saved to: {summary_file}")
    print(json.dumps(results, indent=2))
    print(f"========================================\n")
    if errors:
        raise MetricsIncomplete("; ".join(f"{name}: {msg}" for name, msg in errors.items()))
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified Metrics Calculator for Microservice Partitioning")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to dataset directory (contains dataset.json)")
    parser.add_argument("--output-path", type=str, required=True, help="Path to tool output directory (contains output.json)")
    parser.add_argument("--ned-lo", type=int, default=5, help="Lower bound for NED")
    parser.add_argument("--ned-hi", type=int, default=20, help="Upper bound for NED")
    parser.add_argument("--eps", type=float, default=0.5, help="Epsilon factor for NED relative")
    args = parser.parse_args()

    try:
        compute_all_metrics(args.dataset_path, args.output_path, ned_lo=args.ned_lo, ned_hi=args.ned_hi, eps=args.eps)
    except (PartitionError, FileNotFoundError, MetricsIncomplete) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
