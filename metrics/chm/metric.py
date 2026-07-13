# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///

import json
import argparse
import itertools
import os

def calculate_similarity(set_k, set_m):
    """Calculates Jaccard similarity between two sets."""
    if not set_k and not set_m:
        return 1.0  # Both empty -> completely similar
    union_len = len(set_k.union(set_m))
    if union_len == 0:
        return 1.0
    return len(set_k.intersection(set_m)) / union_len

def calculate_chm(processed_result_path, processed_monolith_path, output_path=None):
    """
    Calculates the Cohesion at Message level (CHM).
    Formula from paper considers ONLY externally invoked methods (O_j).
    """
    with open(processed_result_path, 'r', encoding='utf-8') as f:
        result_data = json.load(f)
        microservices = result_data.get("microservices", {})

    with open(processed_monolith_path, 'r', encoding='utf-8') as f:
        monolith_data = json.load(f)
        methods_data = monolith_data.get("methods", {})

    # Create a reverse lookup: method_id -> microservice_id
    method_to_ms = {}
    for ms_id, methods in microservices.items():
        for m in methods:
            method_to_ms[m] = ms_id

    # Identify O_j (externally invoked methods) for each microservice
    # Note: This requires a 'calls' array in the monolith JSON.
    # Since monolith_adapter.py doesn't extract this yet, we will fallback
    # to all methods if 'calls' is missing, but warn the user.
    external_methods_per_ms = {ms_id: set() for ms_id in microservices}
    
    missing_calls_data = False

    for caller_id, m_data in methods_data.items():
        caller_ms = method_to_ms.get(caller_id)
        if not caller_ms:
            continue
            
        calls = m_data.get("calls", None)
        if calls is None:
            missing_calls_data = True
            break
            
        for callee_id in calls:
            callee_ms = method_to_ms.get(callee_id)
            if callee_ms and caller_ms != callee_ms:
                # callee is invoked externally!
                external_methods_per_ms[callee_ms].add(callee_id)

    if missing_calls_data:
        print("WARNING: 'calls' graph not found in monolith data.")
        print("Falling back to evaluating ALL methods (like MAGNET's buggy implementation).")
        for ms_id, methods in microservices.items():
            external_methods_per_ms[ms_id] = set(methods)

    chm_values = {}
    for ms_id, oj_methods in external_methods_per_ms.items():
        if len(oj_methods) > 1:
            pairs = list(itertools.combinations(oj_methods, 2))
            f_msg_sum = 0
            
            for m1, m2 in pairs:
                m1_data = methods_data.get(m1, {})
                m2_data = methods_data.get(m2, {})
                
                ret1 = set([m1_data.get("return_type", "void")])
                ret2 = set([m2_data.get("return_type", "void")])
                par1 = set(m1_data.get("parameters", []))
                par2 = set(m2_data.get("parameters", []))
                
                f_msg = calculate_similarity(ret1, ret2) + calculate_similarity(par1, par2)
                f_msg_sum += f_msg
            
            # Normalizing by number of pairs (as done in MAGNET source code) to keep score 0-2
            chm_values[ms_id] = f_msg_sum / len(pairs)
        else:
            # If |O_j| == 1 or 0, cohesion of pairs is 0
            chm_values[ms_id] = 0.0

    if len(chm_values) == 0:
        final_chm = 0.0
    else:
        final_chm = sum(chm_values.values()) / len(chm_values)
        
    print(f"Final CHM Score: {final_chm:.4f}")
    
    if output_path:
        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                "metric": "CHM",
                "score": final_chm,
                "microservice_scores": chm_values
            }, f, indent=4)
        print(f"Saved metric results to {output_path}")

    return final_chm

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Metric: Evaluator for CHM")
    parser.add_argument("--dataset-path", type=str, required=True, help="Path to the dataset directory (contains dataset.json)")
    parser.add_argument("--output-path", type=str, required=True, help="Path to the tool output directory (contains output.json)")
    
    args = parser.parse_args()
    
    dataset_json = os.path.join(args.dataset_path, "dataset.json")
    output_json = os.path.join(args.output_path, "output.json")
    chm_score_json = os.path.join(args.output_path, "chm_score.json")
    
    calculate_chm(output_json, dataset_json, chm_score_json)
