"""The simulator is its own package (#172, PR A2): the direction of imports, read from the source
files themselves (no import is executed, no network, no data).

1. Nothing in ``src/pickandroll/`` outside ``sim/``, and nothing in ``scripts/``, imports
   ``pickandroll.sim``.
2. Inside the simulator only ``engine.py`` imports ``pickandroll.season``: the engine is called
   through that one door.
3. Inside the simulator only ``readers.py``, ``gamelogs.py`` and ``cli.py`` import
   ``pickandroll.sources``.
4. The simulator's imports from ``pickandroll.api`` are exactly the pairs in :data:`API_TIES`.

Relative and absolute forms count alike, and so do imports inside a function and
``importlib.import_module`` or ``__import__`` with a literal name.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
SIM = SRC / "pickandroll" / "sim"

#: The simulator's imports from the live API, as (simulator module, API module). Each is a tie
#: to the live league (its recorded state, its knob file, its settings) that PR D's standalone
#: cut removes; the list is empty after PR D. A pair not listed here fails the test, and so does
#: a listed pair the code no longer has: the list is a ledger, kept exact.
API_TIES = {
    ("pickandroll.sim.cli", "pickandroll.api.leagues"),
    ("pickandroll.sim.cli", "pickandroll.api.season_knobs"),
    ("pickandroll.sim.cli", "pickandroll.api.season_week"),
    ("pickandroll.sim.cli", "pickandroll.api.seasons"),
    ("pickandroll.sim.readers", "pickandroll.api.season_decisions"),
    ("pickandroll.sim.readers", "pickandroll.api.season_moves"),
    ("pickandroll.sim.readers", "pickandroll.api.season_record"),
    ("pickandroll.sim.readers", "pickandroll.api.season_scorecard"),
    ("pickandroll.sim.readers", "pickandroll.api.seasons"),
}


def module_of(path: Path, src: Path = SRC) -> str:
    parts = list(path.relative_to(src).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def is_module(name: str, src: Path = SRC) -> bool:
    base = src.joinpath(*name.split("."))
    return base.with_suffix(".py").is_file() or (base / "__init__.py").is_file()


def imports_of(source: str, module: str, package: bool, src: Path = SRC) -> set[str]:
    """Every module ``source`` imports, by absolute name, wherever the import sits. ``from X
    import y`` counts ``X.y`` where that is a module of the tree, else ``X``."""
    here = module.split(".") if package else module.split(".")[:-1]
    out: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = here[: len(here) - node.level + 1]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            for a in node.names:
                sub = f"{target}.{a.name}"
                out.add(sub if is_module(sub, src) else target)
        elif isinstance(node, ast.Call) and node.args:
            f = node.func
            name = (
                f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
            )
            arg = node.args[0]
            literal = isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            if name in {"import_module", "__import__"} and literal:
                out.add(arg.value)
    return out


def table(files: list[Path], src: Path = SRC) -> dict[str, set[str]]:
    return {
        module_of(p, src): imports_of(
            p.read_text(), module_of(p, src), p.name == "__init__.py", src
        )
        for p in files
    }


def within(name: str, package: str) -> bool:
    return name == package or name.startswith(package + ".")


def sim_table() -> dict[str, set[str]]:
    return table(sorted(SIM.rglob("*.py")))


def test_the_walker_reads_every_form_of_import(tmp_path):
    pkg = tmp_path / "pickandroll"
    for rel in ("sim/__init__.py", "sim/cli.py", "sim/run.py", "api/__init__.py", "api/x.py"):
        (pkg / rel).parent.mkdir(parents=True, exist_ok=True)
        (pkg / rel).write_text("")
    source = (
        "import os\n"
        "from . import run as rn\n"
        "from .run import f\n"
        "from ..api import x\n"
        "from ..api.x import thing\n"
        "import pickandroll.season.moves\n"
        "def later():\n"
        "    from ..sources.bbm import load\n"
        "    import importlib\n"
        "    return importlib.import_module('pickandroll.season.weekly')\n"
    )
    got = imports_of(source, "pickandroll.sim.cli", False, tmp_path)
    assert got == {
        "os",
        "importlib",
        "pickandroll.sim.run",
        "pickandroll.api.x",
        "pickandroll.season.moves",
        "pickandroll.sources.bbm",
        "pickandroll.season.weekly",
    }
    # A package's own relative imports start from the package itself.
    assert imports_of("from . import run\n", "pickandroll.sim", True, tmp_path) == {
        "pickandroll.sim.run"
    }


def test_the_walker_sees_the_simulators_real_imports():
    """Not vacuous: the door, the readers' function-level imports and the commands' own."""
    t = sim_table()
    assert {"pickandroll.season.moves", "pickandroll.season.weekly"} <= t["pickandroll.sim.engine"]
    assert {"pickandroll.sources.bbm", "pickandroll.sources.matching"} <= t[
        "pickandroll.sim.readers"
    ]
    assert "pickandroll.sim.engine" in t["pickandroll.sim.policy"]
    assert "pickandroll.api.season_knobs" in t["pickandroll.sim.cli"]  # inside a function


def test_nothing_outside_the_simulator_imports_it():
    outside = [p for p in sorted((SRC / "pickandroll").rglob("*.py")) if SIM not in p.parents]
    found = {
        (m, i) for m, names in table(outside).items() for i in names if within(i, "pickandroll.sim")
    }
    scripts = sorted((ROOT / "scripts").rglob("*.py"))
    for p in scripts:
        found |= {
            (str(p.relative_to(ROOT)), i)
            for i in imports_of(p.read_text(), p.stem, False)
            if within(i, "pickandroll.sim")
        }
    assert outside and scripts
    assert found == set(), f"the simulator is imported from outside it: {sorted(found)}"


def test_only_the_door_imports_the_engine():
    found = {
        (m, i)
        for m, names in sim_table().items()
        for i in names
        if within(i, "pickandroll.season") and m != "pickandroll.sim.engine"
    }
    assert found == set(), f"the engine is reached around sim/engine.py: {sorted(found)}"


def test_only_the_readers_and_the_commands_import_the_sources():
    allowed = {"pickandroll.sim.readers", "pickandroll.sim.gamelogs", "pickandroll.sim.cli"}
    found = {
        (m, i)
        for m, names in sim_table().items()
        for i in names
        if within(i, "pickandroll.sources") and m not in allowed
    }
    assert found == set(), f"a core module imports pickandroll.sources: {sorted(found)}"


def test_the_ties_to_the_live_api_are_exactly_the_ledger():
    found = {
        (m, i) for m, names in sim_table().items() for i in names if within(i, "pickandroll.api")
    }
    assert found - API_TIES == set(), f"a new tie to the live API: {sorted(found - API_TIES)}"
    assert API_TIES - found == set(), f"a tie the code no longer has: {sorted(API_TIES - found)}"
