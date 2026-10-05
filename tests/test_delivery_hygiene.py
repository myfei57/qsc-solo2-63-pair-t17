"""Delivery hygiene gate: no scaffolding, no dead code, no project narration."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "bagsort"

RUNTIME_HOOKS = {
    "__init__",
    "__post_init__",
    "__enter__",
    "__exit__",
    "__repr__",
    "__eq__",
    "__hash__",
    "__call__",
    "__slots__",
    "do_GET",
    "do_POST",
    "do_PUT",
    "do_DELETE",
    "log_message",
    "main",
}

# Tokens that would give away where this tree came from. They are assembled from
# fragments so this checker does not itself contain the strings it looks for.
FORBIDDEN_TOKENS = (
    "zxy" + "-",
    "设计" + "文档",
    "本" + "项目是",
    "本" + "仓库是",
    "design" + " doc",
    "design" + "_doc",
    "ben" + "zhi",
)

# Directories that are not part of the shipped delivery tree.
UNSCANNED = {".git", "__pycache__", ".pytest_cache", ".smoke", "var", "tests"}


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _sources() -> dict[str, ast.AST]:
    trees: dict[str, ast.AST] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        trees[_module_name(path)] = ast.parse(path.read_text(encoding="utf-8"), str(path))
    return trees


def _definitions(tree: ast.AST, module: str) -> list[dict]:
    found: list[dict] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append({"name": node.name, "module": module, "line": node.lineno})
        elif isinstance(node, ast.ClassDef):
            found.append({"name": node.name, "module": module, "line": node.lineno})
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append({"name": item.name, "module": module, "line": item.lineno})
    return found


def _usages(tree: ast.AST) -> list[str]:
    used: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.append(node.id)
        elif isinstance(node, ast.Attribute):
            used.append(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for part in node.value.replace("/", ".").replace("-", ".").split("."):
                if part.isidentifier():
                    used.append(part)
    return used


def _resolve(module: str, node: ast.ImportFrom, is_package: bool) -> list[str]:
    base = node.module or ""
    if node.level:
        parts = module.split(".")
        parent = parts if is_package else parts[:-1]
        keep = max(0, len(parent) - (node.level - 1))
        base = ".".join(parent[:keep] + ([base] if base else []))
    resolved = [base] if base else []
    for alias in node.names:
        if alias.name != "*":
            resolved.append(f"{base}.{alias.name}" if base else alias.name)
    return [item for item in resolved if item]


def _is_package(module: str) -> bool:
    return (ROOT / module.replace(".", "/") / "__init__.py").is_file()


def _graph(modules: dict[str, ast.AST]) -> dict[str, set[str]]:
    packages = {name for name in modules if _is_package(name)}
    graph: dict[str, set[str]] = {name: set() for name in modules}
    for name, tree in modules.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                graph[name].update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                graph[name].update(_resolve(name, node, name in packages))
    return graph


def test_no_unreferenced_symbols():
    usages: dict[str, int] = {}
    definitions: list[dict] = []
    for module, tree in _sources().items():
        definitions.extend(_definitions(tree, module))
        for name in _usages(tree):
            usages[name] = usages.get(name, 0) + 1
    orphans = [
        item
        for item in definitions
        if usages.get(item["name"], 0) == 0
        and item["name"] not in RUNTIME_HOOKS
        and not item["module"].endswith("__main__")
    ]
    assert orphans == [], f"symbols generated but never wired up: {orphans}"


def test_every_module_is_reachable_from_the_entrypoint():
    modules = _sources()
    graph = _graph(modules)
    pending = [name for name in modules if name.endswith("__main__")]
    assert pending, "the package needs an __main__ entry point"
    reachable: set[str] = set()
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        for target in graph.get(current, set()):
            candidates = [target]
            parts = target.split(".")
            for cut in range(len(parts) - 1, 0, -1):
                candidates.append(".".join(parts[:cut]))
            for candidate in candidates:
                if candidate in modules and candidate not in reachable:
                    pending.append(candidate)
    unreachable = sorted(
        name for name in modules if name not in reachable and not name.endswith("__main__")
    )
    assert unreachable == [], f"modules nobody loads: {unreachable}"


def _protocol_classes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and any(
            (isinstance(base, ast.Name) and base.id == "Protocol")
            or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
            for base in node.bases
        ):
            ids.add(id(node))
    return ids


def test_no_placeholder_function_bodies():
    places: list[str] = []
    for module, tree in _sources().items():
        protocols = _protocol_classes(tree)
        protocol_methods = {
            id(item)
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef) and id(node) in protocols
            for item in node.body
        }
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if id(node) in protocol_methods:
                continue
            body = [
                item
                for item in node.body
                if not (isinstance(item, ast.Expr) and isinstance(item.value, ast.Constant))
            ]
            if len(body) != 1:
                continue
            only = body[0]
            if isinstance(only, ast.Pass):
                places.append(f"{module}:{node.lineno} {node.name} is only pass")
            elif isinstance(only, ast.Return) and only.value is None:
                places.append(f"{module}:{node.lineno} {node.name} is an empty return")
            elif (
                isinstance(only, ast.Expr)
                and isinstance(only.value, ast.Constant)
                and only.value.value is Ellipsis
            ):
                places.append(f"{module}:{node.lineno} {node.name} is only an ellipsis")
    assert places == [], f"placeholder implementations: {places}"


def test_package_ships_no_readme():
    names = {path.name.lower() for path in ROOT.iterdir()}
    assert not any(name.startswith("readme") for name in names)
    assert not (PACKAGE / "README.md").exists()


def test_project_metadata_stays_neutral():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'description = "line service"' in pyproject
    assert (PACKAGE / "__init__.py").read_text(encoding="utf-8").strip().endswith('__all__ = ["__version__"]')


def test_delivery_tree_carries_no_project_narration():
    offenders: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        parts = set(path.relative_to(ROOT).parts)
        if parts & UNSCANNED:
            continue
        if path.is_dir() or path.suffix in {".pyc", ".png", ".jpg", ".xlsx", ".zip"}:
            continue
        try:
            text = path.read_text(encoding="utf-8").lower()
        except (UnicodeDecodeError, OSError):
            continue
        for token in FORBIDDEN_TOKENS:
            if token in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {token!r}")
    assert offenders == [], f"delivery tree leaks project provenance: {offenders}"


def test_every_handler_is_reachable_from_the_route_table():
    from bagsort.console import handlers
    from bagsort.console.routes import route_table

    registered = {route.handler for route in route_table()}
    defined = {
        name for name in dir(handlers) if name.startswith("handle_") and callable(getattr(handlers, name))
    }
    assert defined - registered == set(), "handlers exist that no route reaches"
    assert registered - defined == set(), "routes point at missing handlers"
