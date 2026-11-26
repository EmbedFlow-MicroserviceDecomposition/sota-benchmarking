"""Adapter: dataset.json -> CHGNN input folder (data_layer/utilities/data/<name>_AE_EGCN_Separate/).

Generated files:
    temp/inter_class_usage.json   CALL/FIELD weights, EXTENDS, IMPLEMENTS (every edge type counts as usage)
    temp/callgraph.dot            class-level "method" graph with entrypoint annotations (one fake method
                                  <Class>.call per class); per entrypoint E, every CALL/FIELD edge inside E's
                                  reachable set is emitted with E's annotation
    temp/service.json             one entry per entrypoint class
    temp/db.json                  from a {class: {table: "CRUD"}} map
    custom/seeds.txt              copied from the dataset's config dir
    custom/ignore_classes.txt     copied (or empty)
    custom/gcnconfig_<code>.json  template with num_clusters = #seed lines and
                                  node_dimension = 2*(#classes + #tables) + #entrypoints

Per-dataset config (tools/chgnn/configs/<dataset>/): dbmap.json, seeds.txt, [ignore_classes.txt]. Entrypoints are dataset
facts shared with other tools and come from datasets/<dataset>/entrypoints.txt (passed as entrypoints_file).
"""

import json
import os
from collections import defaultdict

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gcnconfig_template.json")


def load_graph(dataset):
    """(sorted class FQNs, [(src, dst, type, int weight)]) from a dataset.json dict."""
    classes = set(dataset.get("classes", ())) | {mid.rsplit(".", 1)[0] for mid in dataset.get("methods", {})}
    edges = []
    for e in dataset.get("edges", []):
        classes.update((e["src"], e["dst"]))
        edges.append((e["src"], e["dst"], e["type"], int(float(e["weight"]))))
    return sorted(classes), edges


def build_icu(nodes, edges):
    """inter_class_usage.json: CALL+FIELD weights as usage counts,
    EXTENDS -> superClass, IMPLEMENTS -> implementedInterfaces."""
    used = defaultdict(lambda: defaultdict(int))
    used_by = defaultdict(lambda: defaultdict(int))
    super_class = {}
    interfaces = defaultdict(list)
    node_set = set(nodes)

    for src, dst, etype, w in edges:
        if src not in node_set or dst not in node_set:
            continue
        # every edge type counts as usage: CHGNN's own acme data lists all
        # EXTENDS/IMPLEMENTS targets in the usage counts too, and classes
        # with a zero usage row (pure inheritance parents) NaN the GCN
        used[src][dst] += w
        used_by[dst][src] += w
        if etype == "EXTENDS":
            super_class[src] = dst
        elif etype == "IMPLEMENTS":
            interfaces[src].append(dst)

    return {
        n: {
            "name": n,
            "usedClassesToCount": dict(used[n]),
            "usedByClassesToCount": dict(used_by[n]),
            "type": "both",
            "superClass": super_class.get(n, "java.lang.Object"),
            "implementedInterfaces": sorted(interfaces[n]),
        }
        for n in nodes
    }


def _ep_annotation(entry_class):
    """Annotation string must be unique per entrypoint CLASS — two classes
    sharing a simple name (admin/web PostController) would otherwise merge
    into one entrypoint and silently shrink CHGNN's EP feature width."""
    short = entry_class.split(".")[-1]
    return ("{type: web, method: GET, uri: [/%s], entry: %s, "
            "entrydisplayname: %s.call}" % (short, entry_class, entry_class))


# edge types that carry call-graph reachability: real calls plus FIELD (DI
# wiring - frameworks inject the field, then dispatch through it, and e.g.
# Spring Data repositories receive no project-level CALL edges at all)
_LINK_TYPES = ("CALL", "FIELD")


def reachable(edges, root):
    """Classes reachable from root via CALL/FIELD edges (root included)."""
    out = defaultdict(set)
    for src, dst, etype, _ in edges:
        if etype in _LINK_TYPES:
            out[src].add(dst)
    seen = {root}
    stack = [root]
    while stack:
        for nxt in out[stack.pop()] - seen:
            seen.add(nxt)
            stack.append(nxt)
    return seen


def build_callgraph_dot(nodes, edges, entrypoints):
    lines = ["digraph {", "rankdir=LR", "node[shape=plaintext]"]
    for ep_class in entrypoints:
        ann = _ep_annotation(ep_class)
        lines.append('"%s.call" -> "[%s] %s.call"' % (ep_class, ann, ep_class))
        reach = reachable(edges, ep_class)
        for src, dst, etype, _ in edges:
            if etype in _LINK_TYPES and src in reach and dst in reach:
                lines.append('"[%s] %s.call" -> "[%s] %s.call"'
                             % (ann, src, ann, dst))
    lines.append("}")
    return "\n".join(lines) + "\n"


def build_service_json(entrypoints):
    return [
        {
            "service_entry_name": _ep_annotation(ep),
            "class_method_name": ["%s.call" % ep],
        }
        for ep in entrypoints
    ]


def build_db_json(db_map):
    """db_map: {class_fqn: {table_name: "CRUD letters"}} -> db.json entries."""
    entries = []
    for cls, tables in db_map.items():
        for table, crud in tables.items():
            for letter in crud:
                entries.append({
                    "service_name": "%s.call" % cls,
                    "db_name": table,
                    "crud": letter,
                })
    return entries


def _lines(path):
    with open(path) as f:
        return [line.strip() for line in f if line.strip()]


def _require_classes(names, known, where):
    missing = sorted(n for n in names if n not in known)
    if missing:
        raise ValueError("%s lists classes that are not in dataset.json: %s" % (where, ", ".join(missing)))


def build_chgnn_inputs(dataset, config_dir, out_dir, code="with_edge_loss", template=None, entrypoints_file=None):
    nodes, edges = load_graph(dataset)
    known = set(nodes)

    entrypoints = _lines(entrypoints_file or os.path.join(config_dir, "entrypoints.txt"))
    with open(os.path.join(config_dir, "dbmap.json")) as f:
        db_map = json.load(f)
    with open(os.path.join(config_dir, "seeds.txt")) as f:
        seed_lines = [line for line in f if line.strip()]
    ignore_path = os.path.join(config_dir, "ignore_classes.txt")
    configured_ignore = _lines(ignore_path) if os.path.exists(ignore_path) else []

    _require_classes(entrypoints, known, "entrypoints.txt")
    _require_classes(db_map, known, "dbmap.json")
    seed_classes = [n.strip() for line in seed_lines for n in line.split(",") if n.strip()]
    _require_classes([n for n in seed_classes if not n.endswith("-res")], known, "seeds.txt")

    # stale entries (class not in this checkout) are dropped; classes with no edges at all have a zero usage row
    # and NaN CHGNN's GCN, so they are excluded too unless the config itself names them
    stale = sorted(n for n in configured_ignore if n not in known)
    if stale:
        print("note: dropping ignore_classes.txt entries not in dataset.json: " + ", ".join(stale))
    linked = {c for e in edges for c in e[:2]}
    protected = set(entrypoints) | set(db_map) | set(seed_classes)
    ignore = sorted({n for n in configured_ignore if n in known} | (known - linked - protected))

    with open(template or TEMPLATE) as f:
        config = json.load(f)
    tables = sorted({t for tabs in db_map.values() for t in tabs})

    os.makedirs(os.path.join(out_dir, "temp"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "custom"), exist_ok=True)

    def write(rel, content):
        with open(os.path.join(out_dir, rel), "w") as f:
            f.write(content)

    write("temp/inter_class_usage.json", json.dumps(build_icu(nodes, edges), indent=1))
    write("temp/callgraph.dot", build_callgraph_dot(nodes, edges, entrypoints))
    write("temp/service.json", json.dumps(build_service_json(entrypoints), indent=1))
    write("temp/db.json", json.dumps(build_db_json(db_map), indent=1))
    write("custom/seeds.txt", "".join(seed_lines))
    write("custom/ignore_classes.txt", "".join(n + "\n" for n in ignore))

    config["code"] = "_" + code
    config["num_clusters"] = len(seed_lines)
    # INH and PCC are (classes+resources) wide, EP is one column per entrypoint
    config["node_dimension"] = 2 * (len(nodes) + len(tables)) + len(entrypoints)
    write("custom/gcnconfig_%s.json" % code, json.dumps(config, indent=1))
