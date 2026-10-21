import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for sub in ("datasets", "metrics"):
    sys.path.insert(0, str(ROOT / sub))


def load_tool(tool_dir):
    """Import tools/<tool_dir>/tool.py under a unique module name (every tool has a tool.py)."""
    import importlib.util

    path = ROOT / "tools" / tool_dir / "tool.py"
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location("tool_" + tool_dir.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
