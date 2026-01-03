from future import annotations

import importlib
import inspect
import sys
from pathlib import Path
from typing import Any, Dict, List

----------------------------------------------------------------------
Project root and import setup
----------------------------------------------------------------------

THIS_FILE = Path(file).resolve()
PROJECT_ROOT = THIS_FILE.parents[1] # .../backbone_skeleton

if str(PROJECT_ROOT) not in sys.path:
sys.path.insert(0, str(PROJECT_ROOT))

----------------------------------------------------------------------
Spec: what we expect to exist in core modules
----------------------------------------------------------------------
This is your "anti-drift contract". If we later refactor core modules,
we update this spec and re-run the diagnostics to see what broke.

MODULE_SPECS: List[Dict[str, Any]] = [
{
"name": "backbone.chunking.chunk",
"required_classes": ["Chunk", "MergedChunk"],
"required_functions": [], # top-level functions only
"label": "Core chunk primitives",
},
{
"name": "backbone.chunking.chunker",
"required_classes": ["Chunker"],
"required_functions": [],
"label": "Main chunker orchestrator",
},
{
"name": "backbone.chunking.semantic_grouper",
"required_classes": [],
"required_functions": ["group_chunks_by_semantics"],
"label": "Semantic note grouping",
},
{
"name": "backbone.chunking.column_detector",
"required_classes": ["ColumnDetector"],
"required_functions": [],
"label": "Column assignment logic",
},
{
"name": "backbone.visual.visual_pipeline_integrator",
"required_classes": ["VisualPipelineIntegrator"],
"required_functions": [],
"label": "JSON annotation -> PDF alignment",
},
{
"name": "backbone.visual.visual_chunker_bridge",
"required_classes": ["VisualChunkerBridge"],
"required_functions": [],
"label": "Attach visual metadata to chunks",
},
]

----------------------------------------------------------------------
Helpers
----------------------------------------------------------------------

def _inspect_module(mod_name: str) -> Dict[str, Any]:
"""
Import a module by name and return:
{
"ok": bool,
"error": Optional[str],
"classes": [names],
"functions": [names],
}
"""
result: Dict[str, Any] = {
"ok": False,
"error": None,
"classes": [],
"functions": [],
}

try:
    mod = importlib.import_module(mod_name)
except Exception as exc:
    result["error"] = f"import failed: {exc}"
    return result

# Classes and functions actually defined in this module
classes = [
    name for name, obj in inspect.getmembers(mod, inspect.isclass)
    if getattr(obj, "__module__", None) == mod.__name__
]
functions = [
    name for name, obj in inspect.getmembers(mod, inspect.isfunction)
    if getattr(obj, "__module__", None) == mod.__name__
]

result["ok"] = True
result["classes"] = classes
result["functions"] = functions
return result


def _check_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
"""
Compare actual module contents against the spec.
Returns:
{
"module": str,
"label": str,
"ok": bool,
"problems": [str],
"classes": [...],
"functions": [...],
"error": Optional[str]
}
"""
mod_name = spec["name"]
label = spec.get("label", "")
required_classes = spec.get("required_classes", [])
required_functions = spec.get("required_functions", [])

info = _inspect_module(mod_name)
problems: List[str] = []

if not info["ok"]:
    problems.append(info["error"] or "unknown import error")
    return {
        "module": mod_name,
        "label": label,
        "ok": False,
        "problems": problems,
        "classes": [],
        "functions": [],
        "error": info["error"],
    }

classes = info["classes"]
functions = info["functions"]

# Check required classes
for cls in required_classes:
    if cls not in classes:
        problems.append(f"missing required class: {cls}")

# Check required functions
for fn in required_functions:
    if fn not in functions:
        problems.append(f"missing required function: {fn}")

return {
    "module": mod_name,
    "label": label,
    "ok": not problems,
    "problems": problems,
    "classes": classes,
    "functions": functions,
    "error": None,
}

----------------------------------------------------------------------
Main diagnostic flow
----------------------------------------------------------------------

def main() -> None:
print(">>> CORE INTEGRATION DIAGNOSTIC")
print(f">>> Project root: {PROJECT_ROOT}")
print(">>> This script only inspects modules; it does not modify any files.\n")

results: List[Dict[str, Any]] = []
any_errors = False

for spec in MODULE_SPECS:
    mod_name = spec["name"]
    label = spec.get("label", "")
    print("------------------------------------------------------------")
    print(f"MODULE: {mod_name}")
    if label:
        print(f"ROLE:   {label}")

    res = _check_spec(spec)
    results.append(res)

    if res["error"]:
        print(f"  IMPORT ERROR: {res['error']}")
        any_errors = True
        continue

    print(f"  Classes found:   {', '.join(res['classes']) or '(none)'}")
    print(f"  Functions found: {', '.join(res['functions']) or '(none)'}")

    if res["ok"]:
        print("  STATUS: OK (all required classes/functions present)")
    else:
        any_errors = True
        print("  STATUS: PROBLEMS")
        for p in res["problems"]:
            print(f"    - {p}")

# Summary
print("\n============================================================")
print("SUMMARY")
print("============================================================")

if not results:
    print("No modules were checked. Something is wrong with MODULE_SPECS.")
    return

if not any_errors:
    print("All core modules imported successfully and matched the expected API surface.")
else:
    print("Issues detected in the following modules:")
    for res in results:
        if res["ok"]:
            continue
        label = f" ({res['label']})" if res["label"] else ""
        print(f" - {res['module']}{label}")
        for p in res["problems"]:
            print(f"     -> {p}")


if name == "main":
main()