# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "javalang",
# ]
# ///

import os
import json
import argparse
import javalang

def extract_method_info(file_path):
    """
    Parses a Java file and extracts method signatures (return types and parameters).
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        source_code = f.read()

    try:
        tree = javalang.parse.parse(source_code)
    except javalang.parser.JavaSyntaxError:
        print(f"Syntax error in {file_path}. Skipping.")
        return []
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return []

    package_name = tree.package.name if tree.package else ""
    methods_data = []

    for path, node in tree.filter(javalang.tree.ClassDeclaration):
        class_name = node.name
        for method in node.methods:
            method_name = method.name
            
            # Extract return type
            return_type = method.return_type.name if method.return_type and hasattr(method.return_type, 'name') else "void"
            
            # Extract parameter types
            parameters = []
            for param in method.parameters:
                if isinstance(param.type, javalang.tree.ReferenceType):
                    parameters.append(param.type.name)
                elif hasattr(param.type, 'name'):
                    parameters.append(param.type.name)
                else:
                    parameters.append("Unknown")

            # Construct a fully qualified name (e.g., com.acmeair.service.FlightService.getFlight)
            fqn = f"{package_name}.{class_name}.{method_name}" if package_name else f"{class_name}.{method_name}"

            methods_data.append({
                "id": fqn,
                "class": class_name,
                "package": package_name,
                "method_name": method_name,
                "return_type": return_type,
                "parameters": parameters,
                "file_path": file_path
            })

    return methods_data

def generate_universal_json(source_dir, output_file):
    """
    Scans the dataset directory for Java files and generates the Universal JSON representation.
    """
    print(f"Scanning {source_dir} for Java files...")
    all_methods = {}

    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".java"):
                file_path = os.path.join(root, file)
                extracted_methods = extract_method_info(file_path)
                for m in extracted_methods:
                    # We use the base method ID to ensure compatibility with decomposition tools.
                    # Overloaded methods will collide, which matches standard tool behavior.
                    method_id = m['id']
                    all_methods[method_id] = m

    xmi_path = 'acmeair-unified_kdm.xmi'

    output_data = {
        "dataset": "Acme Air",
        "source_path": os.path.relpath(source_dir),
        "build_path": "acmeair/acmeair-webapp/build/libs/acmeair-webapp-2.0.0-SNAPSHOT.war",
        "xmi_path": xmi_path,
        "methods": all_methods
    }

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=4)
    
    print(f"Successfully extracted {len(all_methods)} methods.")
    print(f"Universal JSON saved to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dataset: Monolith Adapter for Acme Air")
    parser.add_argument("--source_dir", type=str, default="acmeair-unified", help="Path to the monolithic source code")
    parser.add_argument("--output", type=str, default="dataset.json", help="Output path for the Universal JSON")
    
    args = parser.parse_args()
    generate_universal_json(args.source_dir, args.output)
