"""SAM connection refusal must degrade, not load the in-process model.

The analyzer imports Django, so this checks the handler with the AST
instead of calling it.
"""

from __future__ import annotations

import ast
from pathlib import Path

SAM = Path(__file__).resolve().parents[1] / "sam.py"


def _connection_handlers(tree: ast.AST) -> list[ast.ExceptHandler]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        typ = node.type
        name = typ.attr if isinstance(typ, ast.Attribute) else getattr(typ, "id", None)
        if name == "ConnectionError":
            found.append(node)
    return found


def test_connection_error_returns_unavailable_response():
    tree = ast.parse(SAM.read_text(encoding="utf-8"))
    handlers = _connection_handlers(tree)
    assert len(handlers) == 1, "expected one ConnectionError handler"
    returns = [n for n in handlers[0].body if isinstance(n, ast.Return)]
    assert returns, "ConnectionError must return instead of falling through"
    call = returns[0].value
    assert isinstance(call, ast.Call)
    assert isinstance(call.func, ast.Name)
    assert call.func.id == "_unavailable_response"
    reasons = [
        kw.value.value
        for kw in call.keywords
        if kw.arg == "reason" and isinstance(kw.value, ast.Constant)
    ]
    assert reasons == ["connection_error"]
