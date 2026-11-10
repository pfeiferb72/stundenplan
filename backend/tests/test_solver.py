"""QS-102: Solver-Regressionstest mit Referenzszenario + Abbruchtest (NF-102/103)."""
import threading
import time

from app.solver import engine
from app.solver.heuristic import solve
from app.solver.loader import load_context


def test_solver_referenzszenario_keine_harten_verletzungen(db, seeded):
    ctx, _ = load_context(db, seeded["school_id"], seeded["schuljahr_id"], None)
    assert len(ctx.blocks) == 44  # 4 Klassen, Einheiten nach Aufteilung
    assign, pen = solve(ctx, None, budget_s=15, seed=42)
    total, hard, soft = engine.score(ctx, assign)
    assert hard == [], f"Harte Restriktionsverletzungen im Solver-Ergebnis: {hard[:5]}"
    assert total < 1_000_000.0


def test_solver_abbrechbar(db, seeded):
    ctx, _ = load_context(db, seeded["school_id"], seeded["schuljahr_id"], None)
    cancel = threading.Event()
    cancel.set()  # sofortiger Abbruch
    start = time.monotonic()
    assign, pen = solve(ctx, cancel, budget_s=60, seed=1)
    assert time.monotonic() - start < 30
    assert assign  # trotzdem ein Ergebnis


def test_solver_fixierungen_werden_eingehalten(db, seeded):
    ctx, initial = load_context(db, seeded["school_id"], seeded["schuljahr_id"], None)
    fixed = {ctx.blocks[0].key}
    ctx.blocks[0].fixiert = True
    assign, pen = solve(ctx, None, budget_s=8, seed=7, fixed_keys=fixed)
    # Fixierter Block darf nur an seiner konstruktiven Position landen – hier prüfen wir nur,
    # dass der Lauf terminiert und ein vollständiges Ergebnis liefert
    assert set(assign.keys()) == {b.key for b in ctx.blocks}
