"""Static checks on the scripts in scripts/.

Every other test imports modules from src/portfolio. Nothing exercised the
scripts you actually type commands at, so the wiring layer had no coverage at
all - and two bugs lived there:

  * run_cycle.py called execute() without its `universe` argument. It would
    have raised TypeError at the exact moment it tried to trade, during the
    first live cycle, by hand, on a Monday morning.
  * run_cycle.py told the user to run scripts/stamp_inception.py, which did
    not exist.

These are static: they parse the scripts rather than importing them, because
importing alpaca.py raises without credentials and CI runs tests without them.
"""

from __future__ import annotations

import ast
import io
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((REPO / "scripts").glob("*.py"))
MODULES = sorted((REPO / "src" / "portfolio").glob("*.py"))


def _tree(path):
    return ast.parse(io.open(path, encoding="utf-8").read(), filename=str(path))


def _signatures():
    """name -> (required positional count, accepts **kwargs, arg names)."""
    out = {}
    for module in MODULES:
        for node in _tree(module).body:
            if isinstance(node, ast.FunctionDef):
                args = node.args
                names = [a.arg for a in args.posonlyargs + args.args]
                required = len(names) - len(args.defaults)
                out[node.name] = (required, names, bool(args.kwarg))
    return out


def test_every_script_parses():
    for script in SCRIPTS:
        _tree(script)


def test_calls_match_signatures():
    """Catch a caller passing too few arguments to one of our own functions.

    This is exactly the run_cycle.py bug: execute() gained a `universe`
    parameter and one caller was never updated.
    """
    signatures = _signatures()
    problems = []

    for script in SCRIPTS:
        for node in ast.walk(_tree(script)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in signatures:
                continue
            required, arg_names, _ = signatures[name]
            supplied = len(node.args) + len(node.keywords)
            if any(k.arg is None for k in node.keywords):
                continue                        # **kwargs splat, cannot count statically
            if supplied < required:
                given = [a.arg for a in node.keywords if a.arg]
                problems.append(
                    f"{script.name}:{node.lineno} calls {name}() with {supplied} "
                    f"argument(s); it requires {required} ({', '.join(arg_names)}). "
                    f"Keywords given: {given or 'none'}"
                )

    assert not problems, "\n".join(problems)


def test_referenced_scripts_exist():
    """A script that tells the user to run another script must not be lying.

    run_cycle.py printed 'python scripts/stamp_inception.py' when that file did
    not exist - and printed it at the one moment it mattered, right after the
    first live orders were submitted.
    """
    missing = []
    for script in SCRIPTS:
        text = io.open(script, encoding="utf-8").read()
        for token in text.split():
            cleaned = token.strip("\"'`,.:()")
            if cleaned.startswith("scripts/") and cleaned.endswith(".py"):
                if not (REPO / cleaned).is_file():
                    missing.append(f"{script.name} references {cleaned}, which does not exist")
    assert not missing, "\n".join(missing)
