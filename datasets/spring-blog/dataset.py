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
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        source_code = f.read()

    try:
        tree = javalang.parse.parse(source_code)
    except Exception:
        return []

    package_name = tree.package.name if tree.package else ""
    imports = {}
    if tree.imports:
        for imp in tree.imports:
            imp_path = imp.path
            short_name = imp_path.split(".")[-1]
            imports[short_name] = imp_path

    methods_data = []

    for path, class_node in tree.filter(javalang.tree.ClassDeclaration):
        class_name = class_node.name
        class_fqn = f"{package_name}.{class_name}" if package_name else class_name

        field_types = {}
        for field in class_node.fields:
            ftype = field.type.name if hasattr(field.type, "name") else str(field.type)
            full_type = imports.get(ftype, f"{package_name}.{ftype}" if package_name else ftype)
            for var in field.declarators:
                field_types[var.name] = full_type

        for method in class_node.methods:
            method_name = method.name
            return_type = method.return_type.name if method.return_type and hasattr(method.return_type, "name") else "void"
            
            parameters = []
            param_types = {}
            for param in method.parameters:
                ptype = param.type.name if hasattr(param.type, "name") else "Unknown"
                parameters.append(ptype)
                param_types[param.name] = imports.get(ptype, f"{package_name}.{ptype}" if package_name else ptype)

            fqn = f"{package_name}.{class_name}.{method_name}" if package_name else f"{class_name}.{method_name}"

            calls = []
            if method.body:
                for _, inv in method.filter(javalang.tree.MethodInvocation):
                    inv_name = inv.member
                    qualifier = inv.qualifier

                    if qualifier:
                        target_cls = param_types.get(qualifier, field_types.get(qualifier, imports.get(qualifier, qualifier)))
                        calls.append(f"{target_cls}.{inv_name}")
                    else:
                        calls.append(f"{class_fqn}.{inv_name}")

            methods_data.append({
                "id": fqn,
                "class": class_name,
                "package": package_name,
                "method_name": method_name,
                "return_type": return_type,
                "parameters": parameters,
                "calls": calls,
                "file_path": file_path
            })

    return methods_data

def generate_universal_json(dataset_name, source_dir, output_file, build_path, xmi_path):
    print(f"Scanning {source_dir} for Java files...")
    all_methods = {}
    edges_set = set()
    edges = []

    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".java"):
                file_path = os.path.join(root, file)
                extracted_methods = extract_method_info(file_path)
                for m in extracted_methods:
                    method_id = m["id"]
                    all_methods[method_id] = m

                    caller_cls = m["class"]
                    caller_pkg = m.get("package", "")
                    caller_fqn = f"{caller_pkg}.{caller_cls}" if caller_pkg else caller_cls

                    for callee in m.get("calls", []):
                        callee_cls = callee.rsplit(".", 1)[0] if "." in callee else callee
                        edge_key = (caller_fqn, callee_cls)
                        if edge_key not in edges_set and caller_fqn != callee_cls:
                            edges_set.add(edge_key)
                            edges.append({
                                "src": caller_fqn,
                                "dst": callee_cls,
                                "type": "CALL",
                                "weight": 1.0
                            })

    usecases = {}
    out_dir = os.path.dirname(output_file) if os.path.dirname(output_file) else "."
    usecase_json_path = os.path.join(out_dir, "usecases.json")
    if os.path.exists(usecase_json_path):
        try:
            with open(usecase_json_path, "r", encoding="utf-8") as f:
                usecases = json.load(f)
        except Exception:
            pass

    output_data = {
        "dataset": dataset_name,
        "source_path": os.path.relpath(source_dir),
        "build_path": build_path,
        "xmi_path": xmi_path,
        "methods": all_methods,
        "edges": edges,
        "usecases": usecases
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=4)
    
    print(f"Successfully extracted {len(all_methods)} methods and {len(edges)} edges for {dataset_name}.")
    print(f"Universal JSON saved to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dataset: Monolith Adapter")
    parser.add_argument("--source_dir", type=str, default="SpringBlog", help="Path to monolithic source code")
    parser.add_argument("--output", type=str, default="dataset.json", help="Output path for Universal JSON")
    args = parser.parse_args()
    generate_universal_json("Spring Blog", args.source_dir, args.output, "spring-blog/target/spring-blog.jar", "spring-blog_kdm.xmi")
