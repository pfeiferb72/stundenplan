"""Restriktions-Engine (FD-204 harte / FD-205 weiche Restriktionen, Score FD-305).

Reine Logik ohne DB-Zugriff: arbeitet auf einem PlanContext und einer Belegung
{block_key: Placement}. Unit-testbar (QS-101). Es gibt eine schnelle Single-Pass-
Variante (_evaluate) für die Solver-Loop und detaillierte Varianten für API/Report.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HARD_PENALTY = 1_000_000.0


@dataclass
class Block:
    key: str
    veranstaltung_id: int
    klasse_id: int
    schuelerzahl: int
    stammraum_id: int | None
    gegenstand_code: str
    benoetigt_fachraum: bool
    benoetigte_ausstattung: list
    kopplungsgruppe: str | None
    laenge: int
    fix_lehrkraft_id: int | None
    fixiert: bool


@dataclass
class Placement:
    day: int
    slot: int
    raum_id: int
    lehrkraft_id: int


@dataclass
class TeacherInfo:
    id: int
    lehrverpflichtung: float
    max_tagesstunden: int
    qualifikationen: list
    sperrzeiten: dict
    wunschfenster: dict
    unterrichtsfreie_tage: list


@dataclass
class RoomInfo:
    id: int
    name: str
    kapazitaet: int
    ausstattung: list
    fachraum: bool


@dataclass
class PlanContext:
    tage: int
    slots: int
    max_am_stueck: int
    mittagsgrenze_slot: int
    gewichte: dict
    blocks: list[Block] = field(default_factory=list)
    teachers: dict[int, TeacherInfo] = field(default_factory=dict)
    rooms: dict[int, RoomInfo] = field(default_factory=dict)
    klassen_stammraum: dict[int, int | None] = field(default_factory=dict)

    def weight(self, key: str) -> float:
        return float(self.gewichte.get(key, 0.0))


def parse_aufteilung(aufteilung: str, wochenstunden: int) -> list[int]:
    """"2+1" -> [2, 1]; Summe muss wochenstunden ergeben (FD-201)."""
    try:
        parts = [int(p) for p in aufteilung.split("+") if p.strip()]
    except ValueError:
        parts = []
    if not parts or sum(parts) != wochenstunden:
        parts = [1] * wochenstunden
    return parts


def expand_blocks(veranstaltungen: list[dict]) -> list[Block]:
    blocks: list[Block] = []
    for v in veranstaltungen:
        for i, laenge in enumerate(parse_aufteilung(v["aufteilung"], v["wochenstunden"])):
            blocks.append(Block(
                key=f"{v['id']}:{i}",
                veranstaltung_id=v["id"],
                klasse_id=v["klasse_id"],
                schuelerzahl=v["schuelerzahl"],
                stammraum_id=v["stammraum_id"],
                gegenstand_code=v["gegenstand_code"],
                benoetigt_fachraum=v["benoetigt_fachraum"],
                benoetigte_ausstattung=v["benoetigte_ausstattung"],
                kopplungsgruppe=v["kopplungsgruppe"],
                laenge=laenge,
                fix_lehrkraft_id=v["lehrkraft_id"],
                fixiert=bool(v.get("fixiert")),
            ))
    return blocks


def _block_slots(block_len: int, start: int) -> range:
    return range(start, start + block_len)


def is_teacher_available(t: TeacherInfo, day: int, slot: int) -> bool:
    if day in (t.unterrichtsfreie_tage or []):
        return False
    for s, e in (t.sperrzeiten.get(str(day), []) or []):
        if s <= slot <= e:
            return False
    return True


def room_suitable(room: RoomInfo, b: Block) -> bool:
    if room.kapazitaet < b.schuelerzahl:
        return False
    if b.benoetigt_fachraum and not room.fachraum:
        return False
    if not set(b.benoetigte_ausstattung).issubset(set(room.ausstattung)):
        return False
    return True


def teacher_qualified(t: TeacherInfo, code: str) -> bool:
    return not t.qualifikationen or code in t.qualifikationen


# ---------------------------------------------------------------- schnelle Variante

def _evaluate(ctx: PlanContext, assign: dict[str, Placement]) -> tuple[int, float]:
    """Single-Pass: (Anzahl harter Verletzungen, Summe weicher Strafpunkte)."""
    nhard = 0
    soft = 0.0
    blocks = ctx.blocks
    n = len(blocks)
    placements = [assign.get(b.key) for b in blocks]

    # Raster + Referenzen
    for b, p in zip(blocks, placements):
        if p is None:
            nhard += 1
            continue
        if p.day < 0 or p.day >= ctx.tage or p.slot < 0 or p.slot + b.laenge > ctx.slots:
            nhard += 1
        if p.raum_id not in ctx.rooms or p.lehrkraft_id not in ctx.teachers:
            nhard += 1

    # Doppelbelegung über Belegungsmatrizen
    occ_t: dict[tuple, int] = {}
    occ_c: dict[tuple, int] = {}
    occ_r: dict[tuple, int] = {}
    for b, p in zip(blocks, placements):
        if p is None:
            continue
        for s in _block_slots(b.laenge, p.slot):
            k = (p.day, s)
            occ_t[(k, p.lehrkraft_id)] = occ_t.get((k, p.lehrkraft_id), 0) + 1
            occ_c[(k, b.klasse_id)] = occ_c.get((k, b.klasse_id), 0) + 1
            occ_r[(k, p.raum_id)] = occ_r.get((k, p.raum_id), 0) + 1
    nhard += sum(v - 1 for v in occ_t.values() if v > 1)
    nhard += sum(v - 1 for v in occ_c.values() if v > 1)
    nhard += sum(v - 1 for v in occ_r.values() if v > 1)

    # Raumeignung, Qualifikation, Verfügbarkeit
    for b, p in zip(blocks, placements):
        if p is None:
            continue
        room = ctx.rooms.get(p.raum_id)
        if room is not None and not room_suitable(room, b):
            nhard += 1
        t = ctx.teachers.get(p.lehrkraft_id)
        if t is None:
            continue
        if not teacher_qualified(t, b.gegenstand_code):
            nhard += 1
        for s in _block_slots(b.laenge, p.slot):
            if not is_teacher_available(t, p.day, s):
                nhard += 1
                break

    # Kopplung
    groups: dict[str, list] = {}
    for b, p in zip(blocks, placements):
        if p is not None and b.kopplungsgruppe:
            groups.setdefault(b.kopplungsgruppe, []).append((p.day, p.slot))
    for g, times in groups.items():
        if len(set(times)) > 1:
            nhard += 1

    # Tageslast, Stückelung, Lehrverpflichtung
    td: dict[tuple, list] = {}
    wl: dict[int, float] = {}
    for b, p in zip(blocks, placements):
        if p is None:
            continue
        td.setdefault((p.lehrkraft_id, p.day), []).extend(_block_slots(b.laenge, p.slot))
        wl[p.lehrkraft_id] = wl.get(p.lehrkraft_id, 0.0) + b.laenge
    for (tid, day), slots in td.items():
        t = ctx.teachers.get(tid)
        if not t:
            continue
        if len(slots) > t.max_tagesstunden:
            nhard += 1
        slotset = set(slots)
        run = best = 0
        for s in range(ctx.slots):
            if s in slotset:
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best > ctx.max_am_stueck:
            nhard += 1
    fixed_teachers = {b.fix_lehrkraft_id for b in blocks if b.fix_lehrkraft_id}
    for tid, t in ctx.teachers.items():
        if tid in fixed_teachers or tid in wl:
            if wl.get(tid, 0.0) != t.lehrverpflichtung:
                nhard += 1

    # weiche Restriktionen
    w = ctx.gewichte
    if w:
        per_class_day: dict[tuple, list] = {}
        per_teacher_day: dict[tuple, set] = {}
        for b, p in zip(blocks, placements):
            if p is None:
                continue
            per_class_day.setdefault((b.klasse_id, p.day), []).extend(_block_slots(b.laenge, p.slot))
            per_teacher_day.setdefault((p.lehrkraft_id, p.day), set()).update(_block_slots(b.laenge, p.slot))
            t = ctx.teachers.get(p.lehrkraft_id)
            if t and p.day in (t.unterrichtsfreie_tage or []):
                soft += float(w.get("unterrichtsfreier_tag", 0.0))
            if p.slot >= ctx.mittagsgrenze_slot:
                soft += float(w.get("fach_vor_mittag", 0.0))
            if t and t.wunschfenster:
                fenster = t.wunschfenster.get(str(p.day), [])
                if fenster and not any(v <= p.slot <= e for v, e in fenster):
                    soft += float(w.get("nicht_wunschfenster", 0.0))
            stamm = ctx.klassen_stammraum.get(b.klasse_id)
            if stamm and p.raum_id != stamm:
                soft += float(w.get("grundraum_abweichung", 0.0))
        fach_day: dict[tuple, dict] = {}
        for b, p in zip(blocks, placements):
            if p is None:
                continue
            fach_day.setdefault((b.klasse_id, p.day), {})
            fach_day[(b.klasse_id, p.day)][b.gegenstand_code] = \
                fach_day[(b.klasse_id, p.day)].get(b.gegenstand_code, 0) + 1
        for (kid, day), slots in per_class_day.items():
            sset = set(slots)
            if sset:
                loecher = (max(sset) - min(sset) + 1) - len(sset)
                if loecher > 0:
                    soft += float(w.get("loch_schueler", 0.0)) * loecher
                if max(sset) == ctx.slots - 1:
                    soft += float(w.get("letzte_stunde", 0.0))
        for (kid, day), faecher in fach_day.items():
            for code, cnt in faecher.items():
                if cnt > 1:
                    soft += float(w.get("fachstreuung", 0.0)) * (cnt - 1)
        for (tid, day), sset in per_teacher_day.items():
            for s in range(ctx.slots):
                if s in sset and (s - 1) not in sset and (s + 1) not in sset:
                    soft += float(w.get("kein_pausenabstand_lehrer", 0.0))
    return nhard, soft


def fast_penalty(ctx: PlanContext, assign: dict[str, Placement]) -> float:
    nhard, soft = _evaluate(ctx, assign)
    return nhard * HARD_PENALTY + soft


def placement_ok(ctx: PlanContext, assign: dict[str, Placement], b: Block, p: Placement,
                 by_key: dict[str, Block] | None = None) -> bool:
    """Inkrementelle harte Prüfung nur für einen Block (für die konstruktive Phase)."""
    if p.day < 0 or p.day >= ctx.tage or p.slot < 0 or p.slot + b.laenge > ctx.slots:
        return False
    room = ctx.rooms.get(p.raum_id)
    t = ctx.teachers.get(p.lehrkraft_id)
    if room is None or t is None:
        return False
    if not room_suitable(room, b) or not teacher_qualified(t, b.gegenstand_code):
        return False
    if b.fix_lehrkraft_id is not None and p.lehrkraft_id != b.fix_lehrkraft_id:
        return False
    for s in _block_slots(b.laenge, p.slot):
        if not is_teacher_available(t, p.day, s):
            return False
    by_key = by_key if by_key is not None else {x.key: x for x in ctx.blocks}
    day_load = 0
    day_slots: set[int] = set()
    wl = 0.0
    new_slots = set(_block_slots(b.laenge, p.slot))
    for other, q in assign.items():
        ob = by_key.get(other)
        if ob is None:
            continue
        if q.lehrkraft_id == p.lehrkraft_id:
            wl += ob.laenge
            if q.day == p.day:
                day_load += ob.laenge
                day_slots.update(_block_slots(ob.laenge, q.slot))
        if q.day == p.day and not (q.slot + ob.laenge <= p.slot or p.slot + b.laenge <= q.slot):
            if q.lehrkraft_id == p.lehrkraft_id or q.raum_id == p.raum_id or ob.klasse_id == b.klasse_id:
                return False
        if ob.kopplungsgruppe and ob.kopplungsgruppe == b.kopplungsgruppe and (q.day, q.slot) != (p.day, p.slot):
            return False
    if day_load + b.laenge > t.max_tagesstunden:
        return False
    if new_slots & day_slots:
        return False
    merged = day_slots | new_slots
    run = best = 0
    for s in range(ctx.slots):
        if s in merged:
            run += 1
            best = max(best, run)
        else:
            run = 0
    if best > ctx.max_am_stueck:
        return False
    if b.fix_lehrkraft_id is None and wl + b.laenge > t.lehrverpflichtung:
        return False
    return True


# ---------------------------------------------------------------- detaillierte Varianten

def hard_violations(ctx: PlanContext, assign: dict[str, Placement]) -> list[dict]:
    """FD-204: harte Restriktionen mit Details. Leere Liste = Plan zulässig."""
    out: list[dict] = []
    by_key = {b.key: b for b in ctx.blocks}
    for key, p in assign.items():
        b = by_key.get(key)
        if b is None:
            continue
        if p.day < 0 or p.day >= ctx.tage or p.slot < 0 or p.slot + b.laenge > ctx.slots:
            out.append({"code": "raster", "block": key, "message": f"Block {key} außerhalb des Zeitrasters"})
        if p.raum_id not in ctx.rooms:
            out.append({"code": "raum_unbekannt", "block": key, "message": f"Raum {p.raum_id} unbekannt"})
        if p.lehrkraft_id not in ctx.teachers:
            out.append({"code": "lehrkraft_unbekannt", "block": key, "message": f"Lehrkraft {p.lehrkraft_id} unbekannt"})

    for category, get_id in (
        ("lehrkraft", lambda k, p: p.lehrkraft_id),
        ("klasse", lambda k, p: by_key[k].klasse_id),
        ("raum", lambda k, p: p.raum_id),
    ):
        seen: dict[tuple, list[str]] = {}
        for key, p in assign.items():
            b = by_key.get(key)
            if b is None:
                continue
            for s in _block_slots(b.laenge, p.slot):
                seen.setdefault((p.day, s, get_id(key, p)), []).append(key)
        for (day, slot, rid), keys in seen.items():
            if len(keys) > 1:
                out.append({"code": f"doppelbelegung_{category}", "day": day, "slot": slot,
                            "resource_id": rid, "blocks": sorted(keys),
                            "message": f"Doppelbelegung {category} {rid} Tag {day} Slot {slot}"})

    for key, p in assign.items():
        b = by_key.get(key)
        if b is None:
            continue
        room = ctx.rooms.get(p.raum_id)
        if room and not room_suitable(room, b):
            out.append({"code": "raumeignung", "block": key, "raum_id": p.raum_id,
                        "message": f"Raum {room.name} nicht geeignet für Block {key}"})
        t = ctx.teachers.get(p.lehrkraft_id)
        if not t:
            continue
        if not teacher_qualified(t, b.gegenstand_code):
            out.append({"code": "nicht_qualifiziert", "block": key, "lehrkraft_id": p.lehrkraft_id,
                        "message": f"Lehrkraft {p.lehrkraft_id} nicht qualifiziert für {b.gegenstand_code}"})
        for s in _block_slots(b.laenge, p.slot):
            if not is_teacher_available(t, p.day, s):
                out.append({"code": "nicht_verfuegbar", "block": key, "lehrkraft_id": p.lehrkraft_id,
                            "day": p.day, "slot": s, "message": "Lehrkraft nicht verfügbar"})
                break

    groups: dict[str, list[tuple[str, Placement]]] = {}
    for key, p in assign.items():
        b = by_key.get(key)
        if b and b.kopplungsgruppe:
            groups.setdefault(b.kopplungsgruppe, []).append((key, p))
    for g, items in groups.items():
        first = items[0][1]
        if any((p.day, p.slot) != (first.day, first.slot) for _, p in items[1:]):
            out.append({"code": "kopplung", "gruppe": g, "blocks": [k for k, _ in items],
                        "message": f"Koppelgruppe {g} nicht zur selben Zeit"})

    per_teacher_day: dict[tuple[int, int], list[tuple[str, Placement, Block]]] = {}
    for key, p in assign.items():
        b = by_key.get(key)
        if b:
            per_teacher_day.setdefault((p.lehrkraft_id, p.day), []).append((key, p, b))
    for (tid, day), items in per_teacher_day.items():
        t = ctx.teachers.get(tid)
        if not t:
            continue
        total = sum(b.laenge for _, _, b in items)
        if total > t.max_tagesstunden:
            out.append({"code": "max_tagesstunden", "lehrkraft_id": tid, "day": day,
                        "message": f"Lehrkraft {tid}: {total} Std. an Tag {day} (max {t.max_tagesstunden})"})
        slots = set()
        for _, p, b in items:
            slots.update(_block_slots(b.laenge, p.slot))
        run = best = 0
        for s in range(ctx.slots):
            if s in slots:
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best > ctx.max_am_stueck:
            out.append({"code": "max_am_stueck", "lehrkraft_id": tid, "day": day,
                        "message": f"Lehrkraft {tid}: {best} Std. am Stück (max {ctx.max_am_stueck})"})

    workload: dict[int, float] = {}
    for key, p in assign.items():
        b = by_key.get(key)
        if b:
            workload[p.lehrkraft_id] = workload.get(p.lehrkraft_id, 0.0) + b.laenge
    fixed_teachers = {b.fix_lehrkraft_id for b in ctx.blocks if b.fix_lehrkraft_id}
    for tid, t in ctx.teachers.items():
        if tid in fixed_teachers or tid in workload:
            ist = workload.get(tid, 0.0)
            if ist != t.lehrverpflichtung:
                out.append({"code": "lehrverpflichtung", "lehrkraft_id": tid, "soll": t.lehrverpflichtung,
                            "ist": ist, "message": f"Lehrverpflichtung {tid}: soll {t.lehrverpflichtung}, ist {ist}"})
    return out


def soft_violations(ctx: PlanContext, assign: dict[str, Placement]) -> list[dict]:
    """FD-205: weiche Restriktionen mit Details und Gewichten."""
    out: list[dict] = []
    by_key = {b.key: b for b in ctx.blocks}

    def add(code, wkey, **extra):
        w = ctx.weight(wkey)
        if w:
            out.append({"code": code, "gewicht": w, **extra})

    per_class_day: dict[tuple[int, int], list[tuple[str, Placement, Block]]] = {}
    per_teacher_day: dict[tuple[int, int], set] = {}
    for key, p in assign.items():
        b = by_key.get(key)
        if not b:
            continue
        per_class_day.setdefault((b.klasse_id, p.day), []).append((key, p, b))
        per_teacher_day.setdefault((p.lehrkraft_id, p.day), set()).update(_block_slots(b.laenge, p.slot))
        t = ctx.teachers.get(p.lehrkraft_id)
        if t and p.day in (t.unterrichtsfreie_tage or []):
            add("unterrichtsfreier_tag", "unterrichtsfreier_tag", block=key, lehrkraft_id=p.lehrkraft_id, day=p.day)
        if p.slot >= ctx.mittagsgrenze_slot:
            add("fach_nach_mittag", "fach_vor_mittag", block=key, fach=b.gegenstand_code)
        if t and t.wunschfenster:
            fenster = t.wunschfenster.get(str(p.day), [])
            if fenster and not any(v <= p.slot <= e for v, e in fenster):
                add("nicht_wunschfenster", "nicht_wunschfenster", block=key, lehrkraft_id=p.lehrkraft_id, day=p.day)
        stamm = ctx.klassen_stammraum.get(b.klasse_id)
        if stamm and p.raum_id != stamm:
            add("grundraum_abweichung", "grundraum_abweichung", block=key, klasse_id=b.klasse_id,
                raum_id=p.raum_id, stammraum_id=stamm)

    fach_day: dict[tuple, dict] = {}
    for (kid, day), items in per_class_day.items():
        slots = set()
        for key, p, b in items:
            slots.update(_block_slots(b.laenge, p.slot))
            d = fach_day.setdefault((kid, day), {})
            d[b.gegenstand_code] = d.get(b.gegenstand_code, 0) + 1
        if slots:
            loecher = (max(slots) - min(slots) + 1) - len(slots)
            if loecher > 0:
                add("loch_schueler", "loch_schueler", klasse_id=kid, day=day, anzahl=loecher)
            if max(slots) == ctx.slots - 1:
                add("letzte_stunde", "letzte_stunde", klasse_id=kid, day=day)
    for (kid, day), faecher in fach_day.items():
        for code, cnt in faecher.items():
            if cnt > 1:
                add("fachstreuung", "fachstreuung", klasse_id=kid, day=day, fach=code, anzahl=cnt - 1)
    for (tid, day), sset in per_teacher_day.items():
        for s in range(ctx.slots):
            if s in sset and (s - 1) not in sset and (s + 1) not in sset:
                add("kein_pausenabstand_lehrer", "kein_pausenabstand_lehrer", lehrkraft_id=tid, day=day, slot=s)
    return out


def score(ctx: PlanContext, assign: dict[str, Placement]) -> tuple[float, list[dict], list[dict]]:
    """Score (FD-305): harte Verletzungen mit HARD_PENALTY, weiche mit Gewicht."""
    hard = hard_violations(ctx, assign)
    soft = soft_violations(ctx, assign)
    total = len(hard) * HARD_PENALTY + sum(v["gewicht"] for v in soft)
    return total, hard, soft


def _sig(v: dict) -> tuple:
    return (v.get("code"), v.get("block"), tuple(sorted(v.get("blocks", []))),
            v.get("lehrkraft_id"), v.get("raum_id"), v.get("resource_id"),
            v.get("day"), v.get("slot"), v.get("klasse_id"), v.get("gruppe"))


def validate_move(ctx: PlanContext, assign: dict[str, Placement], key: str, p: Placement) -> dict:
    """Echtzeit-Validierung einer Platzierung (FD-301/FD-209).

    Blockiert nur, wenn die Verschiebung eine NEUE harte Verletzung erzeugt
    (bereits vorhandene Verletzungen des Plans bleiben unberührt);
    weiche Verletzungen der betroffenen Ressource werden als Warnung gemeldet.
    """
    trial = dict(assign)
    trial[key] = p
    by_key = {b.key: b for b in ctx.blocks}
    b = by_key.get(key)
    before = {_sig(v) for v in hard_violations(ctx, assign)}
    after_list = hard_violations(ctx, trial)
    new_sigs = {_sig(v) for v in after_list} - before
    # Lehrverpflichtung ist eine Plan-Gesamtbedingung (FD-204), blockiert aber keine
    # einzelne Platzierung (FD-301) – sie wird im Validierungs-Endpoint berichtet.
    new_sigs = {s for s in new_sigs if s[0] != "lehrverpflichtung"}
    hard = [h for h in after_list if _sig(h) in new_sigs]
    soft = [s for s in soft_violations(ctx, trial)
            if s.get("block") == key or s.get("lehrkraft_id") == p.lehrkraft_id
            or (b is not None and s.get("klasse_id") == b.klasse_id and s.get("day") == p.day)]
    return {"zulaessig": len(new_sigs) == 0, "harte_verletzungen": hard, "warnungen": soft}
