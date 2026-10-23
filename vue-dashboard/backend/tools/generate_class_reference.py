"""Generate the backend class reference without importing application modules."""

from __future__ import annotations

import argparse
import ast
import copy
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
OUTPUT = BACKEND / "docs" / "backend-class-reference.md"


def classes_in(node: ast.AST, scope: str = ""):
    """Include nested and function-local classes, with unambiguous names."""
    for child in ast.iter_child_nodes(node):
        child_scope = scope
        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            child_scope = f"{scope}.{child.name}" if scope else child.name
        if isinstance(child, ast.ClassDef):
            yield child_scope, child
        yield from classes_in(child, child_scope)


def interface(node: ast.ClassDef) -> str:
    """Keep declared members and signatures; omit executable method bodies."""
    result = copy.deepcopy(node)
    members = []
    for member in result.body:
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
            member.body = [ast.Expr(value=ast.Constant(value=Ellipsis))]
            members.append(member)
        elif isinstance(member, (ast.Assign, ast.AnnAssign)):
            members.append(member)
    result.body = members or [ast.Expr(value=ast.Constant(value=Ellipsis))]
    # Unparse preserves decorators, positional/keyword-only arguments, defaults,
    # annotations and base classes. A single-line stub is easier to scan.
    return ast.unparse(result).replace("\n        ...", " ...")


def render() -> tuple[str, int, int]:
    modules = []
    file_count = 0
    for path in sorted((BACKEND / "app").rglob("*.py")):
        file_count += 1
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        classes = list(classes_in(tree))
        if classes:
            modules.append((path.relative_to(BACKEND).as_posix(), classes))
    count = sum(len(classes) for _, classes in modules)
    lines = [
        "# Backend class reference",
        "",
        f"Source inventory: **{count} class definitions in {len(modules)} files**, "
        f"from {file_count} Python files under `vue-dashboard/backend/app`.",
        "",
        "This reference describes the source in the working tree, including "
        "uncommitted files. It includes public, private, nested, and function-local "
        "classes. Tests, migrations, the frontend, and the separate `src/Morelia` "
        "library are outside its scope.",
        "",
        "Each entry links to its defining module and shows bases, decorators, "
        "class-level fields/assignments (including ORM columns, schema fields, and "
        "enum values), and directly declared method signatures. Types and defaults "
        "are copied from source; missing annotations are not inferred. Method "
        "bodies, imports, inherited/generated members, and attributes assigned "
        "inside methods are omitted. Nested classes have separate entries. "
        "Class summaries come from the first paragraph of their docstrings. "
        "Code blocks are interface excerpts, not standalone runnable modules.",
        "",
        "Classes are listed at their definition, not repeated for import aliases "
        "or re-exports. For the canonical runtime import surface, see "
        "[`app/contracts/runtime_protocol.py`](../app/contracts/runtime_protocol.py). "
        "Module-level functions and type aliases are not class definitions and "
        "are outside this inventory.",
        "",
        "The [duration implementation plan](run-now-duration-plan.md) documents "
        "proposed first/last-recorded sample timing and a deadline derived from "
        "start plus requested duration. It extends existing classes; the earlier "
        "`ExecutionWindow`, `StopOutcome`, and `RunLifecycleStore` proposals "
        "are not part of that design. This inventory reflects source definitions, "
        "not planned fields or interfaces.",
        "",
        "Regenerate from the repository root with Python 3.11 or newer:",
        "",
        "```sh",
        "python vue-dashboard/backend/tools/generate_class_reference.py",
        "```",
        "",
        "Use `--check` to detect drift without writing. The generator parses "
        "source with Python's AST; it does not import the backend, load "
        "environment values, connect to a database, or open hardware.",
        "",
        "## File index",
        "",
        "| File | Classes |",
        "| --- | --- |",
    ]
    for index, (path, classes) in enumerate(modules, 1):
        names = ", ".join(f"`{name}`" for name, _ in classes)
        lines.append(f"| [{path}](#module-{index}) | {names} |")
    for index, (path, classes) in enumerate(modules, 1):
        lines.extend(["", f'<a id="module-{index}"></a>', "", f"## `{path}`", ""])
        lines.append(f"[Source](../{path}) · {len(classes)} class definition(s)")
        for name, node in classes:
            lines.extend(["", f"### `{name}`", ""])
            doc = ast.get_docstring(node)
            if doc:
                summary = " ".join(doc.split("\n\n", 1)[0].split())
                # A quoted paragraph keeps extracted documentation distinct.
                lines.extend([f"> {summary}", ""])
            if "." in name:
                lines.extend([f"Declared within `{name.rsplit('.', 1)[0]}`.", ""])
            lines.extend(["```python", f"# {path}", interface(node), "```"])
    return "\n".join(lines) + "\n", count, len(modules)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the reference is stale")
    args = parser.parse_args()
    content, count, modules = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != content:
            print(f"Class reference is stale: {OUTPUT}")
            return 1
        print(f"Class reference is current: {count} classes in {modules} files")
        return 0
    OUTPUT.write_text(content, encoding="utf-8", newline="\n")
    print(f"Wrote {OUTPUT}: {count} classes in {modules} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
