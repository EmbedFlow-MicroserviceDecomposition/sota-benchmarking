"""Launcher for upstream Graph.py that runs it for 1 training run instead of its hard-coded 30.

Usage (cwd = a copy of Monolith-to-Microservices): python run_chgnn.py --model=... --data=... --code=...
The submodule stays untouched; Graph.py's source is patched in memory.
"""
import sys

source = open("Graph.py").read()
patched = source.replace("multiple_runs=30", "multiple_runs=1")
assert patched != source, "Graph.py no longer contains 'multiple_runs=30'; update run_chgnn.py"
sys.argv = ["Graph.py"] + sys.argv[1:]
exec(compile(patched, "Graph.py", "exec"), {"__name__": "__main__", "__file__": "Graph.py"})
