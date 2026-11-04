# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "javalang",
# ]
# ///

import os
import json
import argparse
import hashlib
from pathlib import Path
import subprocess
import shutil
import javalang

def extract_method_info(file_path, strict=False):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        source_code = f.read()

    try:
        tree = javalang.parse.parse(source_code)
    except Exception as exc:
        if strict:
            raise ValueError(f"Cannot parse production source {file_path}: {exc}") from exc
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
        enclosing = [node.name for node in path if isinstance(node, javalang.tree.TypeDeclaration)]
        class_name = ".".join(enclosing + [class_node.name]) if strict else class_node.name
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

def extract_monoembed_types(source_root):
    """Build and invoke the source extractor shipped in this repository."""
    extractor = Path(__file__).resolve().parents[2] / "tools/monoembed/extractor"
    jar = extractor / "target/monoembed-extractor.jar"
    if not shutil.which("java"):
        raise ValueError("MonoEmbed source preparation requires Java; install JDK 17 and Maven")
    if not jar.is_file():
        if not shutil.which("mvn"):
            raise ValueError("MonoEmbed source preparation requires Maven (mvn) and JDK 17 to build the bundled extractor")
        subprocess.run(["mvn", "-q", "-DskipTests", "package"], cwd=extractor, check=True)
    proc = subprocess.run(["java", "-jar", str(jar), str(source_root)],
                          capture_output=True, text=True, check=True)
    return json.loads(proc.stdout), hashlib.sha256(jar.read_bytes()).hexdigest()


def load_monoembed_types(records, source_root):
    """Validate the bundled extractor's type universe against production sources."""
    source_root = Path(source_root).resolve()
    expected, source_hashes = {}, {}
    for path in sorted(source_root.rglob("*.java")):
        source = path.read_text(encoding="utf-8")
        try:
            tree = javalang.parse.parse(source)
        except Exception as exc:
            raise ValueError(f"Cannot parse production source {path}: {exc}") from exc
        source_hashes[path.relative_to(source_root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        package = tree.package.name if tree.package else ""
        for ancestors, node in tree.filter(javalang.tree.TypeDeclaration):
            if any(isinstance(parent, (javalang.tree.MethodDeclaration, javalang.tree.ConstructorDeclaration))
                   for parent in ancestors):
                raise ValueError(f"Local types are unsupported in MonoEmbed preparation: {path}")
            owners = [parent.name for parent in ancestors if isinstance(parent, javalang.tree.TypeDeclaration)]
            fqn = ".".join(([package] if package else []) + owners + [node.name])
            if fqn in expected:
                raise ValueError(f"Duplicate source type: {fqn}")
            expected[fqn] = path.resolve()
    if not expected:
        raise ValueError(f"No Java types found under {source_root}")
    if not isinstance(records, list) or not records:
        raise ValueError("Source extractor must return a nonempty type list")
    sources = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Every extracted type must be an object")
        name, content, file_path = (record.get(key) for key in ("fullName", "content", "filePath"))
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValueError("Every type requires a nonempty fullName")
        name = name.replace("$", ".")
        if name in sources:
            raise ValueError(f"Duplicate MonoEmbed type: {name}")
        if not isinstance(content, str) or not content.strip():
            raise ValueError(f"Empty MonoEmbed content: {name}")
        if not isinstance(file_path, str) or not file_path:
            raise ValueError(f"Missing source filePath: {name}")
        path = Path(file_path)
        path = (source_root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(source_root) or not path.is_file():
            raise ValueError(f"Type source is outside the analyzed checkout or missing: {name}: {path}")
        if expected.get(name) != path:
            raise ValueError(f"Type does not match its production source declaration: {name}")
        sources[name] = content
    if set(sources) != set(expected):
        raise ValueError(f"MonoEmbed class universe differs from production sources; missing: {sorted(set(expected) - set(sources))}")
    commit = subprocess.run(["git", "-C", str(source_root), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "-C", str(source_root), "status", "--porcelain"],
                                capture_output=True, text=True, check=True).stdout.strip())
    return {"classes": sorted(sources), "class_sources": dict(sorted(sources.items())),
            "monoembed": {"extractor": "tools/monoembed/extractor (Spoon 10.1.1)",
                          "source_commit": commit, "source_dirty": dirty,
                          "source_scope": "src/main/java", "source_sha256": source_hashes,
                          "class_sources_sha256": hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()}}


def generate_universal_json(dataset_name, source_dir, output_file, build_path, xmi_path, monoembed=False):
    repo_dir = Path(source_dir).resolve()
    monoembed_data = None
    if monoembed:
        source_dir = repo_dir / "src" / "main" / "java"
        if not source_dir.is_dir():
            raise ValueError(f"Production source directory is missing: {source_dir}")
        records, extractor_hash = extract_monoembed_types(source_dir)
        monoembed_data = load_monoembed_types(records, source_dir)
        monoembed_data["monoembed"]["extractor_sha256"] = extractor_hash
    print(f"Scanning {source_dir} for Java files...")
    all_methods = {}
    edges_set = set()
    edges = []

    for root, _, files in os.walk(source_dir):
        for file in files:
            if file.endswith(".java"):
                file_path = os.path.join(root, file)
                extracted_methods = extract_method_info(file_path, strict=monoembed)
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

    if monoembed_data is not None:
        output_data.update(monoembed_data)
        output_data["source_path"] = os.path.relpath(repo_dir, Path(output_file).resolve().parent)
        missing = {mid.rsplit(".", 1)[0] for mid in all_methods} - set(monoembed_data["classes"])
        if missing:
            raise ValueError(f"Benchmark method owners missing from MonoEmbed inputs: {sorted(missing)}")

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=4)
    
    print(f"Successfully extracted {len(all_methods)} methods and {len(edges)} edges for {dataset_name}.")
    print(f"Universal JSON saved to {output_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dataset: Monolith Adapter")
    parser.add_argument("--source_dir", type=str, default="pharmacy", help="Path to monolithic source code")
    parser.add_argument("--output", type=str, default="dataset.json", help="Output path for Universal JSON")
    parser.add_argument("--monoembed", action="store_true", help="Include source inputs using the bundled MonoEmbed extractor (JDK 17 + Maven)")
    args = parser.parse_args()
    generate_universal_json("Pharmacy", args.source_dir, args.output, "pharmacy/target/pharmacy.jar", "pharmacy_kdm.xmi", args.monoembed)
