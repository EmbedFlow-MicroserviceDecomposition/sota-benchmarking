# /// script
# requires-python = ">=3.9"
# dependencies = ["javalang==0.13.0"]
# ///
"""Prepare tool-owned MonoEmbed inputs from a standard benchmark dataset."""

import os
import argparse
import json
import hashlib
from pathlib import Path
import subprocess
import shutil
import javalang

def extract_method_info(file_path, strict=False, fallback_methods=None):
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        source_code = f.read()

    try:
        tree = javalang.parse.parse(source_code)
    except Exception as exc:
        if fallback_methods is not None:
            return fallback_methods
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
        if strict and any(isinstance(node, (javalang.tree.MethodDeclaration, javalang.tree.ConstructorDeclaration, javalang.tree.ClassCreator)) for node in path):
            continue
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
                "file_path": str(file_path)
            })

    return methods_data

def find_source_roots(repo_dir, requested=None):
    """Production Maven roots, then Eclipse src/, with explicit scope overrides."""
    repo_dir = Path(repo_dir).resolve()
    if requested:
        roots = [(repo_dir / path).resolve() for path in requested]
    else:
        ignored = {".git", "target", "build", "node_modules", "test", "tests"}
        roots = sorted(path for path in repo_dir.rglob("java")
                       if path.parts[-3:] == ("src", "main", "java")
                       and not ignored.intersection(path.relative_to(repo_dir).parts[:-3]))
        if not roots:
            roots = [repo_dir / "src"] if (repo_dir / "src").is_dir() else []
    if not roots or any(not root.is_dir() or not root.is_relative_to(repo_dir) for root in roots):
        raise ValueError(f"Production source roots are missing or outside repository: {repo_dir}; initialize its source submodule")
    return roots


def extract_monoembed_types(source_root):
    """Build and invoke the source extractor shipped in this repository."""
    extractor = Path(__file__).resolve().parent / "extractor"
    jar = extractor / "target/monoembed-extractor.jar"
    if not shutil.which("java"):
        raise ValueError("MonoEmbed source preparation requires Java; install JDK 17 and Maven")
    inputs = [extractor / "pom.xml", *extractor.glob("src/main/java/**/*.java")]
    if not jar.is_file() or any(path.is_file() and path.stat().st_mtime > jar.stat().st_mtime for path in inputs):
        if not shutil.which("mvn"):
            raise ValueError("MonoEmbed source preparation requires Maven (mvn) and JDK 17 to build the bundled extractor")
        subprocess.run(["mvn", "-q", "-DskipTests", "package"], cwd=extractor, check=True)
    roots = [source_root] if isinstance(source_root, (str, Path)) else source_root
    proc = subprocess.run(["java", "-jar", str(jar), *map(str, roots)],
                          capture_output=True, text=True, check=True)
    return json.loads(proc.stdout), hashlib.sha256(jar.read_bytes()).hexdigest()


def load_monoembed_types(records, source_root, repo_dir=None):
    """Validate the bundled extractor's type universe against production sources."""
    roots = [Path(source_root).resolve()] if isinstance(source_root, (str, Path)) else [Path(root).resolve() for root in source_root]
    source_root = Path(os.path.commonpath(roots))
    repo_dir = Path(repo_dir).resolve() if repo_dir else source_root
    files = sorted({path.resolve() for root in roots for path in root.rglob("*.java")})
    if not isinstance(records, list) or not records:
        raise ValueError("Source extractor must return a nonempty type list")
    expected, source_hashes, fallback_files = {}, {}, []
    for path in files:
        source = path.read_text(encoding="utf-8")
        source_hashes[path.relative_to(source_root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            tree = javalang.parse.parse(source)
        except Exception as exc:
            # Spoon has already parsed these sources successfully. Require its
            # declared-method records to distinguish this path from old/manual inputs.
            matching = [row for row in records if isinstance(row, dict)
                        and row.get("filePath") and Path(row["filePath"]).resolve() == path]
            if not matching or any(not isinstance(row.get("methods"), list) for row in matching):
                raise ValueError(f"Cannot parse production source {path}: {exc}") from exc
            fallback_files.append(path.relative_to(repo_dir).as_posix())
            for row in matching:
                name = row.get("fullName")
                if not isinstance(name, str) or not name.strip():
                    raise ValueError(f"Invalid Spoon type in {path}")
                name = name.replace("$", ".")
                if name in expected:
                    raise ValueError(f"Duplicate source type: {name}")
                expected[name] = path
            continue
        package = tree.package.name if tree.package else ""
        for ancestors, node in tree.filter(javalang.tree.TypeDeclaration):
            if any(isinstance(parent, (javalang.tree.MethodDeclaration, javalang.tree.ConstructorDeclaration, javalang.tree.ClassCreator))
                   for parent in ancestors):
                continue
            owners = [parent.name for parent in ancestors if isinstance(parent, javalang.tree.TypeDeclaration)]
            fqn = ".".join(([package] if package else []) + owners + [node.name])
            if fqn in expected:
                raise ValueError(f"Duplicate source type: {fqn}")
            expected[fqn] = path.resolve()
    if not expected:
        raise ValueError(f"No Java types found under {source_root}")
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
        if not any(path.is_relative_to(root) for root in roots) or not path.is_file():
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
                          "source_scope": [root.relative_to(repo_dir).as_posix() for root in roots], "source_sha256": source_hashes,
                          "spoon_method_fallback_files": fallback_files,
                          "class_scope": "named top-level and member types (anonymous/local types excluded)",
                          "class_sources_sha256": hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()}}


def build_dataset(dataset_name, source_dir, output_file, build_path, xmi_path, source_roots=None, usecases=None):
    repo_dir = Path(source_dir).resolve()
    roots = find_source_roots(repo_dir, source_roots)
    records, extractor_hash = extract_monoembed_types(roots)
    monoembed_data = load_monoembed_types(records, roots, repo_dir)
    monoembed_data["monoembed"]["extractor_sha256"] = extractor_hash
    fallback_methods = {}
    for record in records:
        if "methods" in record:
            fallback_methods.setdefault(str(Path(record["filePath"]).resolve()), []).extend(record["methods"])
    source_dir = repo_dir
    print(f"Scanning {source_dir} for Java files...")
    all_methods = {}
    edges_set = set()
    edges = []

    for source_root in roots:
        for file_path in sorted(source_root.rglob("*.java")):
            if file_path.is_file():
                extracted_methods = extract_method_info(file_path, strict=True,
                    fallback_methods=fallback_methods.get(str(file_path.resolve())))
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

    read_output_labels = usecases is None
    usecases = {} if usecases is None else usecases
    out_dir = os.path.dirname(output_file) if os.path.dirname(output_file) else "."
    usecase_json_path = os.path.join(out_dir, "usecases.json")
    if read_output_labels and os.path.exists(usecase_json_path):
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

    output_data.update(monoembed_data)
    output_data["source_path"] = os.path.relpath(repo_dir, Path(output_file).resolve().parent)
    missing = {mid.rsplit(".", 1)[0] for mid in all_methods} - set(monoembed_data["classes"])
    if missing:
        raise ValueError(f"Benchmark method owners missing from MonoEmbed inputs: {sorted(missing)}")

    Path(output_file).resolve().parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=4)
    
    print(f"Successfully extracted {len(all_methods)} methods and {len(edges)} edges for {dataset_name}.")
    print(f"Universal JSON saved to {output_file}")
    return output_data



def prepare_dataset(dataset_path, output_path):
    """Leave common dataset metadata intact; write the enriched snapshot under the tool."""
    dataset_path, output_path = Path(dataset_path).resolve(), Path(output_path).resolve()
    metadata = dataset_path / "dataset.json"
    snapshot = output_path / "dataset.json"
    if snapshot.resolve() == metadata.resolve():
        raise ValueError("Use a separate output directory; common dataset.json must not be overwritten")
    # Keep all tool-specific preparation products out of the common datasets tree.
    common_tree = Path(__file__).resolve().parents[2] / "datasets"
    if output_path.is_relative_to(common_tree):
        raise ValueError("MonoEmbed prepared inputs must be outside datasets/; use tools/monoembed/.cache/datasets/<name>")
    if not metadata.is_file():
        if not (dataset_path / "dataset.py").is_file():
            raise ValueError(f"Missing dataset.json and dataset.py in {dataset_path}")
        subprocess.run(["uv", "run", "dataset.py"], cwd=dataset_path, check=True)
    original = json.loads(metadata.read_text(encoding="utf-8"))
    raw_source = original.get("source_path")
    if not raw_source:
        raise ValueError("dataset.json must provide source_path")
    repo = (dataset_path / raw_source).resolve()
    if not repo.is_dir() and not Path(raw_source).is_absolute():
        candidate = (Path(__file__).resolve().parents[2] / raw_source).resolve()
        if candidate.is_dir():
            repo = candidate
    # Acme Air's common adapter uses a flattened Eclipse tree. MonoEmbed uses
    # the pinned upstream modules, with the scope difference recorded in provenance.
    if dataset_path.name == "acme-air":
        repo = dataset_path / "acmeair"
    scope = ("app/src/main/java",) if dataset_path.name == "apache-roller" else None
    usecases = original.get("usecases", {})
    labels = dataset_path / "usecases.json"
    if labels.is_file():
        usecases = json.loads(labels.read_text(encoding="utf-8"))
    if not isinstance(usecases, dict):
        raise ValueError("Use-case mappings must be a class-to-labels object")
    def path_value(key):
        value = original.get(key)
        return str((dataset_path / value).resolve()) if value else ""
    payload = build_dataset(original.get("dataset", dataset_path.name), repo, snapshot,
                            path_value("build_path"), path_value("xmi_path"), scope, usecases)
    payload["monoembed"]["dataset_metadata_sha256"] = hashlib.sha256(metadata.read_bytes()).hexdigest()
    payload["monoembed"]["source_dataset"] = str(dataset_path)
    snapshot.write_text(json.dumps(payload, indent=4) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-path", required=True, help="Common dataset directory")
    parser.add_argument("--output-path", required=True, help="Tool-owned prepared input directory")
    args = parser.parse_args()
    prepare_dataset(args.dataset_path, args.output_path)
