"""Documentation check: new public functions and classes without docstrings."""
import ast

from .diffs import added_lines
from .schemas import Finding


def missing_docstrings(path, source_text, patch):
    """Flag public defs whose definition line was added in this PR and that have no docstring."""
    if not path.endswith(".py"):
        return []
    try:
        tree = ast.parse(source_text)
    except SyntaxError:
        return []
    added = {n for n, _ in added_lines(patch)}
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            if node.lineno in added and not ast.get_docstring(node):
                out.append(Finding(file=path, line=node.lineno, severity="low", category="docs",
                                   message=f"New public {'class' if isinstance(node, ast.ClassDef) else 'function'} '{node.name}' has no docstring.",
                                   suggestion="Add a one-line docstring saying what it does.", source="docs-check",
                                   evidence="parsed with ast"))
    return out
