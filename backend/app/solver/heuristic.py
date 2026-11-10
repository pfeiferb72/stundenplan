"""Solver: konstruktive Startlösung + Simulated Annealing (Metaheuristik, FD-302/303/304).

Läuft asynchron in eigenem Thread (jobs.py), abbrechbar über cancel_event, Fortschritt via on_progress.
"""
from __future__ import annotations

import math
import random
import time

from .engine import (
    Block, Placement, PlanContext, _block_slots, fast_penalty, is_teacher_available,
    placement_ok, room_suitable, teacher_qualified,
)


def _teacher_candidates(ctx: PlanContext, b: Block) -> list[int]:
    if b.fix_lehrkraft_id:
        return [b.fix_lehrkraft_id]
    return [t.id for t in ctx.teachers.values() if teacher_qualified(t, b.gegenstand_code)]


def _constructive(ctx: PlanContext, rng: random.Random) -> dict[str, Placement]:
    """Gierige Startlösung: härteste Blöcke zuerst (Fachraum, große Klassen, Fixierungen)."""
    assign: dict[str, Placement] = {}
    by_key = {b.key: b for b in ctx.blocks}
    blocks = sorted(
        ctx.blocks,
        key=lambda b: (not b.benoetigt_fachraum, -b.schuelerzahl, not b.fix_lehrkraft_id, -b.laenge),
    )
    remaining = {tid: t.lehrverpflichtung for tid, t in ctx.teachers.items()}
    rooms_sorted = sorted(ctx.rooms.values(), key=lambda r: r.name)

    for b in blocks:
        candidates = _teacher_candidates(ctx, b)
        best: tuple | None = None  # (cheap_score, day, slot, raum, lehrer)
        for day in range(ctx.tage):
            for slot in range(ctx.slots - b.laenge + 1):
                for room in rooms_sorted:
                    if not room_suitable(room, b):
                        continue
                    for tid in candidates:
                        t = ctx.teachers[tid]
                        if not all(is_teacher_available(t, day, s) for s in _block_slots(b.laenge, slot)):
                            continue
                        if remaining.get(tid, 0) < b.laenge and b.fix_lehrkraft_id is None:
                            continue
                        p = Placement(day, slot, room.id, tid)
                        if not placement_ok(ctx, assign, b, p, by_key):
                            continue
                        stamm = ctx.klassen_stammraum.get(b.klasse_id)
                        cheap = (0 if stamm == room.id else 1) \
                            + (1 if slot + b.laenge > ctx.slots - 1 else 0) \
                            + slot * 0.01 - remaining.get(tid, 0) * 0.001
                        if best is None or cheap < best[0]:
                            best = (cheap, day, slot, room.id, tid)
                if best is not None and best[0] <= 0.0:
                    break
            if best is not None and best[0] <= 0.0:
                break
        if best is None:
            tid = candidates[0] if candidates else next(iter(ctx.teachers))
            raum_id = next(iter(ctx.rooms))
            best = (float("inf"), 0, 0, raum_id, tid)
        _, day, slot, raum_id, tid = best
        assign[b.key] = Placement(day, slot, raum_id, tid)
        remaining[tid] = remaining.get(tid, 0) - b.laenge
    return assign


def solve(ctx: PlanContext, cancel_event, budget_s: int = 60, seed: int = 0,
          initial: dict[str, Placement] | None = None,
          fixed_keys: set[str] | None = None,
          on_progress=None) -> tuple[dict[str, Placement], float]:
    """Optimiert die Belegung per Simulated Annealing. Liefert (assign, score)."""
    rng = random.Random(seed)
    start = time.monotonic()
    deadline = start + budget_s
    fixed_keys = fixed_keys or set()

    assign = dict(initial) if initial else _constructive(ctx, rng)
    for b in ctx.blocks:
        if b.key not in assign:
            assign[b.key] = Placement(0, 0, next(iter(ctx.rooms)),
                                      b.fix_lehrkraft_id or next(iter(ctx.teachers)))

    movable = [b for b in ctx.blocks if b.key not in fixed_keys]
    best_assign = dict(assign)
    best_pen = fast_penalty(ctx, assign)
    cur_pen = best_pen

    t_start, t_end = 25.0, 0.5
    iteration = 0
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            break
        iteration += 1
        if iteration % 100 == 0 and on_progress:
            on_progress(min(0.99, (time.monotonic() - start) / budget_s))
        if not movable:
            break
        b = rng.choice(movable)
        old = assign[b.key]
        r = rng.random()
        if r < 0.55:  # verschieben
            new = Placement(rng.randrange(ctx.tage), rng.randrange(max(1, ctx.slots - b.laenge + 1)),
                            old.raum_id, old.lehrkraft_id)
            if rng.random() < 0.7:
                new.raum_id = rng.choice(list(ctx.rooms))
        elif r < 0.8 and len(movable) > 1:  # Zeit+Raum mit anderem Block tauschen
            other = rng.choice(movable)
            if other.key == b.key:
                continue
            o = assign[other.key]
            assign[b.key] = Placement(o.day, o.slot, o.raum_id, old.lehrkraft_id)
            assign[other.key] = Placement(old.day, old.slot, old.raum_id, o.lehrkraft_id)
            trial_pen = fast_penalty(ctx, assign)
            temp = t_start * (t_end / t_start) ** ((time.monotonic() - start) / budget_s)
            if trial_pen <= cur_pen or rng.random() < math.exp(-max(trial_pen - cur_pen, -700) / max(temp, 1e-9)):
                cur_pen = trial_pen
                if cur_pen < best_pen:
                    best_pen = cur_pen
                    best_assign = dict(assign)
            else:
                assign[b.key] = old
                assign[other.key] = o
            continue
        else:  # Lehrkraft neu zuweisen
            cands = _teacher_candidates(ctx, b)
            if not cands:
                continue
            new = Placement(old.day, old.slot, old.raum_id, rng.choice(cands))
        assign[b.key] = new
        trial_pen = fast_penalty(ctx, assign)
        temp = t_start * (t_end / t_start) ** ((time.monotonic() - start) / budget_s)
        if trial_pen <= cur_pen or rng.random() < math.exp(-max(trial_pen - cur_pen, -700) / max(temp, 1e-9)):
            cur_pen = trial_pen
            if cur_pen < best_pen:
                best_pen = cur_pen
                best_assign = dict(assign)
        else:
            assign[b.key] = old

    if on_progress:
        on_progress(1.0)
    return best_assign, best_pen
