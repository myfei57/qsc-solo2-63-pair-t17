"""Delivery tree dead code and reachability gate.

Two checks:

1. **Symbol references** — every module level function, class and class method
   in the production package must be referenced somewhere else in the package.
   A symbol that is only defined and never used was generated but not wired up.
2. **Module reachability** — starting from ``bagsort.__main__`` /
   ``bagsort.cli`` and following the import graph, every production module must
   be in the transitive closure. A module outside the closure is a file nobody
   loads.

Usage::

    python tools/deadcode.py bagsort

Exit code 0 means clean, 1 means problems (the findings are printed as JSON).
"""

from __future__ import annotations

import ast
import json
import os
import sys

# Names the runtime or the language calls by convention; not dead symbols.
HOOK_NAMES = {
    "__init__",
    "__post_init__",
    "__enter__",
    "__exit__",
    "__repr__",
    "__eq__",
    "__hash__",
    "__call__",
    "__iter__",
    "__len__",
    "__slots__",
    "__all__",
    "do_GET",
    "do_POST",
    "do_PUT",
    "do_DELETE",
    "log_message",
    "main",
}


def _module_name(path: str, root: str) -> str:
    relative = os.path.relpath(path, os.path.dirname(root))
    parts = relative.replace(os.sep, ".").removesuffix(".py").split(".")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _iter_sources(root: str) -> list[str]:
    sources: list[str] = []
    for base, _dirs, files in os.walk(root):
        if "__pycache__" in base:
            continue
        for name in sorted(files):
            if name.endswith(".py"):
                sources.append(os.path.join(base, name))
    return sorted(sources)


def _collect_definitions(tree: ast.AST, module: str) -> list[dict]:
    found: list[dict] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append(
                {
                    "name": node.name,
                    "qualname": node.name,
                    "module": module,
                    "line": node.lineno,
                    "kind": "function",
                }
            )
        elif isinstance(node, ast.ClassDef):
            found.append(
                {
                    "name": node.name,
                    "qualname": node.name,
                    "module": module,
                    "line": node.lineno,
                    "kind": "class",
                }
            )
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append(
                        {
                            "name": item.name,
                            "qualname": f"{node.name}.{item.name}",
                            "module": module,
                            "line": item.lineno,
                            "kind": "method",
                        }
                    )
    return found


def _collect_usages(tree: ast.AST) -> list[str]:
    used: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.append(node.id)
        elif isinstance(node, ast.Attribute):
            used.append(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # __all__ entries and route handler names are indirect references.
            used.extend(
                part
                for part in node.value.replace("/", ".").replace("-", ".").split(".")
                if part.isidentifier()
            )
    return used


def _resolve_import(module: str, node: ast.ImportFrom, is_package: bool) -> list[str]:
    """Turn a relative import into absolute module names."""

    base = node.module or ""
    if node.level:
        parts = module.split(".")
        parent = parts if is_package else parts[:-1]
        keep = max(0, len(parent) - (node.level - 1))
        prefix = parent[:keep]
        base = ".".join(prefix + ([base] if base else []))
    resolved = [base] if base else []
    for alias in node.names:
        if alias.name == "*":
            continue
        resolved.append(f"{base}.{alias.name}" if base else alias.name)
    return [item for item in resolved if item]


def analyze(root: str) -> dict:
    """Run both checks and return the report."""

    root = os.path.abspath(root)
    sources = _iter_sources(root)
    modules: dict[str, ast.AST] = {}
    packages: set[str] = set()
    for path in sources:
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        module = _module_name(path, root)
        modules[module] = tree
        if os.path.basename(path) == "__init__.py":
            packages.add(module)

    usages: dict[str, int] = {}
    definitions: list[dict] = []
    for module, tree in modules.items():
        definitions.extend(_collect_definitions(tree, module))
        for name in _collect_usages(tree):
            usages[name] = usages.get(name, 0) + 1

    unused = [
        item
        for item in definitions
        if usages.get(item["name"], 0) == 0
        and item["name"] not in HOOK_NAMES
        and not item["module"].endswith("__main__")
    ]

    imports: dict[str, set[str]] = {module: set() for module in modules}
    for module, tree in modules.items():
        is_package = module in packages
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports[module].add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                imports[module].update(_resolve_import(module, node, is_package))

    reachable: set[str] = set()
    pending = [name for name in modules if name.endswith("__main__") or name.endswith(".cli")]
    if not pending:
        pending = [name for name in modules if name.count(".") == 0]
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for target in imports.get(current, set()):
            candidates = [target]
            parts = target.split(".")
            for cut in range(len(parts) - 1, 0, -1):
                candidates.append(".".join(parts[:cut]))
            for candidate in candidates:
                if candidate in modules and candidate not in reachable:
                    pending.append(candidate)

    unreachable_modules = sorted(
        module for module in modules if module not in reachable and not module.endswith("__main__")
    )

    return {
        "root": root,
        "files": len(sources),
        "symbols": len(definitions),
        "unused_symbols": sorted(unused, key=lambda item: (item["module"], item["line"])),
        "unreachable_modules": unreachable_modules,
        "ok": not unused and not unreachable_modules,
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = args[0] if args else "bagsort"
    report = analyze(root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
