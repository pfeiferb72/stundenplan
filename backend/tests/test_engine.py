"""QS-101: Unit-Tests der Restriktions-Engine (vollständige Abdeckung der harten/weichen Regeln)."""
import pytest

from app.solver.engine import (
    Block, Placement, PlanContext, RoomInfo, TeacherInfo, expand_blocks, hard_violations,
    parse_aufteilung, score, soft_violations, validate_move,
)


def make_ctx() -> PlanContext:
    blocks = [
        Block("v1:0", 1, 10, 28, 100, "D", False, [], None, 2, None, False),
        Block("v1:1", 1, 10, 28, 100, "D", False, [], None, 1, None, False),
        Block("v2:0", 2, 11, 28, 101, "POS", True, ["PC"], None, 2, None, False),
        Block("v3:0", 3, 10, 28, 100, "E", False, [], "K1", 1, None, False),
        Block("v4:0", 4, 11, 28, 101, "E", False, [], "K1", 1, None, False),
    ]
    teachers = {
        1: TeacherInfo(1, 5.0, 8, ["D", "E", "POS"], {}, {}, []),
        2: TeacherInfo(2, 3.0, 8, ["POS", "E"], {"0": [[0, 3]]}, {}, [4]),
    }
    rooms = {
        100: RoomInfo(100, "A", 30, [], False),
        101: RoomInfo(101, "B", 30, [], False),
        102: RoomInfo(102, "Labor", 24, ["PC"], True),
    }
    return PlanContext(tage=5, slots=8, max_am_stueck=4, mittagsgrenze_slot=4,
                       gewichte={"loch_schueler": 20.0, "letzte_stunde": 10.0,
                                 "unterrichtsfreier_tag": 50.0, "grundraum_abweichung": 6.0,
                                 "fach_vor_mittag": 5.0},
                       blocks=blocks, teachers=teachers, rooms=rooms,
                       klassen_stammraum={10: 100, 11: 101})


def assign(**kw) -> dict[str, Placement]:
    base = {
        "v1:0": Placement(0, 0, 100, 1), "v1:1": Placement(0, 2, 100, 1),
        "v2:0": Placement(0, 0, 102, 2), "v3:0": Placement(1, 1, 100, 1),
        "v4:0": Placement(1, 1, 101, 1),
    }
    base.update(kw)
    return base


def test_parse_aufteilung():
    assert parse_aufteilung("2+1", 3) == [2, 1]
    assert parse_aufteilung("2+2", 4) == [2, 2]
    assert parse_aufteilung("2+1", 4) == [1, 1, 1, 1]  # inkonsistent -> Einzelstunden
    assert parse_aufteilung("", 2) == [1, 1]


def test_expand_blocks_summe():
    blocks = expand_blocks([{"id": 7, "klasse_id": 1, "schuelerzahl": 20, "stammraum_id": None,
                             "gegenstand_code": "D", "benoetigt_fachraum": False,
                             "benoetigte_ausstattung": [], "kopplungsgruppe": None,
                             "aufteilung": "2+1", "wochenstunden": 3, "lehrkraft_id": None,
                             "fixiert": False}])
    assert [b.laenge for b in blocks] == [2, 1]
    assert sum(b.laenge for b in blocks) == 3


def test_doppelbelegung_lehrkraft():
    ctx = make_ctx()
    a = assign()
    a["v3:0"] = Placement(0, 0, 100, 1)  # Lehrer 1 doppelt bei Tag 0 Slot 0
    codes = [v["code"] for v in hard_violations(ctx, a)]
    assert "doppelbelegung_lehrkraft" in codes


def test_doppelbelegung_raum():
    ctx = make_ctx()
    a = assign()
    a["v3:0"] = Placement(0, 0, 100, 1)  # Raum 100 doppelt (und Lehrer 1)
    codes = [v["code"] for v in hard_violations(ctx, a)]
    assert "doppelbelegung_raum" in codes


def test_doppelbelegung_klasse():
    ctx = make_ctx()
    a = assign()
    a["v1:1"] = Placement(1, 1, 100, 2)  # Klasse 10 doppelt bei Tag 1 Slot 1 (v3:0)
    codes = [v["code"] for v in hard_violations(ctx, a)]
    assert "doppelbelegung_klasse" in codes


def test_raumeignung_kapazitaet_und_fachraum():
    ctx = make_ctx()
    a = assign()
    a["v2:0"] = Placement(2, 2, 100, 2)  # POS braucht Fachraum+PC, Raum 100 hat keins
    codes = [v["code"] for v in hard_violations(ctx, a)]
    assert "raumeignung" in codes
    a2 = assign()
    a2["v2:0"] = Placement(2, 2, 102, 2)
    # Labor kap 24 < 28 Schüler -> nicht geeignet
    codes2 = [v["code"] for v in hard_violations(ctx, a2)]
    assert "raumeignung" in codes2


def test_lehrverpflichtung_exakt():
    ctx = make_ctx()
    a = assign()  # Lehrer 1: 2+1+1+1=5 == soll; Lehrer 2: nur v2:0 -> 2 != soll 3
    v = [x for x in hard_violations(ctx, a) if x["code"] == "lehrverpflichtung"]
    assert len(v) == 1 and v[0]["lehrkraft_id"] == 2 and v[0]["ist"] == 2.0 and v[0]["soll"] == 3.0


def test_max_tagesstunden_und_am_stueck():
    ctx = make_ctx()
    a = assign()
    for i, key in enumerate(["v1:0", "v1:1", "v3:0", "v4:0"]):
        a[key] = Placement(0, i, 100 if key != "v4:0" else 101, 1)  # Lehrer 1: 4+... > 8? -> 2+1+1+1=5 ok
    # jetzt 9 Stunden an einem Tag für Lehrer 1 erzwingen
    blocks_extra = [Block(f"x{i}", 100 + i, 10, 28, 100, "D", False, [], None, 1, None, False)
                    for i in range(6)]
    ctx.blocks.extend(blocks_extra)
    for i, b in enumerate(blocks_extra):
        a[b.key] = Placement(0, i, 100, 1)  # Lehrer 1 hat nun 5+6=11 Std an Tag 0
    codes = [v["code"] for v in hard_violations(ctx, a)]
    assert "max_tagesstunden" in codes


def test_sperrzeit_und_unterrichtsfreier_tag():
    ctx = make_ctx()
    a = assign()
    a["v2:0"] = Placement(0, 1, 102, 2)  # Lehrer 2 gesperrt Tag 0 Slots 0-3
    codes = [v["code"] for v in hard_violations(ctx, a)]
    assert "nicht_verfuegbar" in codes
    a2 = assign()
    a2["v2:0"] = Placement(4, 1, 102, 2)  # Lehrer 2 unterrichtsfrei Fr
    codes2 = [v["code"] for v in hard_violations(ctx, a2)]
    assert "nicht_verfuegbar" in codes2


def test_nicht_qualifiziert():
    ctx = make_ctx()
    a = assign()
    a["v1:0"] = Placement(0, 5, 100, 2)  # Lehrer 2 nicht für D qualifiziert? doch: quals POS,E -> D nicht enthalten
    codes = [v["code"] for v in hard_violations(ctx, a)]
    assert "nicht_qualifiziert" in codes


def test_kopplungsgruppe_gleiche_zeit():
    ctx = make_ctx()
    a = assign()  # v3:0 und v4:0 sind Koppelgruppe K1 -> beide Tag 1 Slot 1 OK
    assert not [v for v in hard_violations(ctx, a) if v["code"] == "kopplung"]
    a["v4:0"] = Placement(2, 3, 101, 1)
    assert any(v["code"] == "kopplung" for v in hard_violations(ctx, a))


def test_weiche_restriktionen_und_score():
    ctx = make_ctx()
    a = assign()
    a["v1:1"] = Placement(0, 7, 100, 1)  # letzte Stunde + evtl. Loch
    total, hard, soft = score(ctx, a)
    soft_codes = [s["code"] for s in soft]
    assert "letzte_stunde" in soft_codes
    assert total == len(hard) * 1_000_000.0 + sum(s["gewicht"] for s in soft)


def test_loch_schueler():
    ctx = make_ctx()
    a = assign()
    # v1:0 belegt Slots 0-1 (Doppelstunde), v1:1 nach Slot 6 -> Loch Slots 2-5 = 4
    a["v1:1"] = Placement(0, 6, 100, 1)
    soft = soft_violations(ctx, a)
    loch = [s for s in soft if s["code"] == "loch_schueler" and s.get("klasse_id") == 10 and s.get("day") == 0]
    assert loch and loch[0]["anzahl"] == 4


def test_validate_move_blockiert_hart_und_warnt_weich():
    ctx = make_ctx()
    a = assign()
    res = validate_move(ctx, a, "v1:1", Placement(0, 0, 100, 1))  # kollidiert mit v1:0
    assert res["zulaessig"] is False and res["harte_verletzungen"]
    res2 = validate_move(ctx, a, "v1:1", Placement(0, 7, 100, 1))  # letzte Stunde -> weich
    assert res2["zulaessig"] is True
    assert any(w["code"] == "letzte_stunde" for w in res2["warnungen"])


def test_rastergrenzen():
    ctx = make_ctx()
    a = assign()
    a["v1:0"] = Placement(0, 7, 100, 1)  # Doppelstunde Slot 7 -> Slot 8 außerhalb (8 Slots)
    codes = [v["code"] for v in hard_violations(ctx, a)]
    assert "raster" in codes
