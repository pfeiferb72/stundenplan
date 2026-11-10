import enum
from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def now() -> datetime:
    return datetime.utcnow()


class Role(str, enum.Enum):
    SYSADMIN = "sysadmin"
    ADMIN = "admin"
    SCHULLEITUNG = "schulleitung"
    PLANER = "planer"
    LEHRKRAFT = "lehrkraft"
    KLASSENKURATOR = "klassenkurator"
    VERWALTUNG = "verwaltung"
    SCHUELER = "schueler"


class PlanStatus(str, enum.Enum):
    ENTWURF = "entwurf"
    PRUEFUNG = "pruefung"
    FREIGABE = "freigabe"
    VEROEFFENTLICHT = "veroeffentlicht"


class StundenZustand(str, enum.Enum):
    GEPLANT = "geplant"
    FREI = "frei"
    ABGESAGT = "abgesagt"
    VERTRETEN = "vertreten"


class AbwesenheitsTyp(str, enum.Enum):
    DIENSTWEG = "dienstweg"
    KRANKHEIT = "krankheit"
    FORTBILDUNG = "fortbildung"
    EXKURSION = "exkursion"
    FREISTELLUNG = "freistellung"


class VertretungsTyp(str, enum.Enum):
    FACHVERTRETUNG = "fachvertretung"
    AUFGABENBETREUUNG = "aufgabenbetreuung"
    ZUSAMMENLEGUNG = "zusammenlegung"
    AUSFALL = "ausfall"


class SolverStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    ABORTED = "aborted"


class Schule(Base):
    __tablename__ = "schule"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    schulart: Mapped[str] = mapped_column(String(20), default="MS")  # VS, MS, AHS, BHS, BS
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    DEFAULT_CONFIG = {
        "tage_pro_woche": 5,
        "slots_pro_tag": 8,
        "slot_dauer_min": 45,
        "erster_slot": "08:00",
        "pausen": [{"nach_slot": 2, "dauer_min": 20}, {"nach_slot": 4, "dauer_min": 10}, {"nach_slot": 6, "dauer_min": 10}],
        "mittagsgrenze_slot": 4,
        "max_stunden_am_stueck": 4,
        "gewichte": {
            "unterrichtsfreier_tag": 50.0,
            "loch_schueler": 20.0,
            "letzte_stunde": 10.0,
            "fach_vor_mittag": 5.0,
            "kein_pausenabstand_lehrer": 15.0,
            "nicht_wunschfenster": 10.0,
            "fachstreuung": 8.0,
            "grundraum_abweichung": 6.0,
            "nicht_stammraum": 4.0,
        },
        "vertretungskaskade": ["fachvertretung", "aufgabenbetreuung", "zusammenlegung", "ausfall"],
    }


class User(Base):
    __tablename__ = "benutzer"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("schule.id"), nullable=True)
    email: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(30), default=Role.LEHRKRAFT.value)
    oidc_sub: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    lehrkraft_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("lehrkraft.id"), nullable=True)
    klasse_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("klasse.id"), nullable=True)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    __table_args__ = (UniqueConstraint("school_id", "email", name="uq_benutzer_school_email"),)


class Schuljahr(Base):
    __tablename__ = "schuljahr"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    bezeichnung: Mapped[str] = mapped_column(String(20))
    start: Mapped[date] = mapped_column(Date)
    ende: Mapped[date] = mapped_column(Date)
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)


class Semester(Base):
    __tablename__ = "semester"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    schuljahr_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schuljahr.id"), index=True)
    bezeichnung: Mapped[str] = mapped_column(String(20))
    start: Mapped[date] = mapped_column(Date)
    ende: Mapped[date] = mapped_column(Date)


class Ressourcenpool(Base):
    __tablename__ = "ressourcenpool"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))


class Raum(Base):
    __tablename__ = "raum"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    name: Mapped[str] = mapped_column(String(50))
    kapazitaet: Mapped[int] = mapped_column(Integer, default=30)
    ausstattung: Mapped[list] = mapped_column(JSONB, default=list)
    fachraum: Mapped[bool] = mapped_column(Boolean, default=False)
    ressourcenpool_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("ressourcenpool.id"), nullable=True)
    gesperrt_bis: Mapped[date | None] = mapped_column(Date, nullable=True)


class Klasse(Base):
    __tablename__ = "klasse"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    schuljahr_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schuljahr.id"), index=True)
    name: Mapped[str] = mapped_column(String(20))
    jahrgang: Mapped[int] = mapped_column(Integer)
    schuelerzahl: Mapped[int] = mapped_column(Integer, default=25)
    stammraum_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("raum.id"), nullable=True)
    teilungsgruppe: Mapped[str | None] = mapped_column(String(50), nullable=True)


class Gegenstand(Base):
    __tablename__ = "gegenstand"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(100))
    schulart: Mapped[str] = mapped_column(String(20), default="MS")
    benoetigt_fachraum: Mapped[bool] = mapped_column(Boolean, default=False)
    benoetigte_ausstattung: Mapped[list] = mapped_column(JSONB, default=list)

    __table_args__ = (UniqueConstraint("school_id", "code", name="uq_gegenstand_code"),)


class Lehrkraft(Base):
    __tablename__ = "lehrkraft"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    vorname: Mapped[str] = mapped_column(String(100))
    nachname: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200))
    lehrverpflichtung: Mapped[float] = mapped_column(Float, default=20.0)  # Wochenstunden (Soll)
    max_tagesstunden: Mapped[int] = mapped_column(Integer, default=8)
    qualifikationen: Mapped[list] = mapped_column(JSONB, default=list)  # Gegenstand-Codes
    sperrzeiten: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"0": [[slot,slot], ...]} 0=Mo
    wunschfenster: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"0": [[von,bis], ...]}
    unterrichtsfreie_tage: Mapped[list] = mapped_column(JSONB, default=list)  # [0..4]
    aktiv: Mapped[bool] = mapped_column(Boolean, default=True)

    @property
    def vollname(self) -> str:
        return f"{self.nachname} {self.vorname}"


class Stundentafel(Base):
    __tablename__ = "stundentafel"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    schulart: Mapped[str] = mapped_column(String(20))
    jahrgang: Mapped[int] = mapped_column(Integer)
    gegenstand_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("gegenstand.id"))
    wochenstunden: Mapped[int] = mapped_column(Integer)
    aufteilung: Mapped[str] = mapped_column(String(20), default="1+1+1")  # z.B. "2+1"
    rhythmus: Mapped[str] = mapped_column(String(5), default="AB")  # A, B, AB


class Unterrichtsveranstaltung(Base):
    __tablename__ = "veranstaltung"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    schuljahr_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schuljahr.id"), index=True)
    klasse_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("klasse.id"), index=True)
    gegenstand_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("gegenstand.id"))
    wochenstunden: Mapped[int] = mapped_column(Integer)
    aufteilung: Mapped[str] = mapped_column(String(20), default="1+1")
    rhythmus: Mapped[str] = mapped_column(String(5), default="AB")
    teilung_nr: Mapped[int] = mapped_column(Integer, default=0)
    kopplungsgruppe: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lehrkraft_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("lehrkraft.id"), nullable=True)
    fixiert: Mapped[bool] = mapped_column(Boolean, default=False)


class Planversion(Base):
    __tablename__ = "planversion"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    schuljahr_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schuljahr.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default=PlanStatus.ENTWURF.value)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    basis_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("planversion.id"), nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("benutzer.id"), nullable=True)
    freigegeben_von: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("benutzer.id"), nullable=True)
    veroeffentlicht_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Stunde(Base):
    __tablename__ = "stunde"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    planversion_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("planversion.id"), index=True)
    veranstaltung_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("veranstaltung.id"))
    wochentag: Mapped[int] = mapped_column(Integer)  # 0=Mo .. 4=Fr
    slot: Mapped[int] = mapped_column(Integer)  # Start-Slot (0-basiert); Doppelstunde belegt slot+1
    laenge: Mapped[int] = mapped_column(Integer, default=1)
    raum_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("raum.id"))
    lehrkraft_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lehrkraft.id"))
    zustand: Mapped[str] = mapped_column(String(20), default=StundenZustand.GEPLANT.value)
    vertretung_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # -> vertretung.id (FK vermieden wegen Zyklus)
    fixiert: Mapped[bool] = mapped_column(Boolean, default=False)


class PlanOperation(Base):
    __tablename__ = "planoperation"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    planversion_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("planversion.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    typ: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSONB)
    undo_payload: Mapped[dict] = mapped_column(JSONB)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("benutzer.id"), nullable=True)
    zeitpunkt: Mapped[datetime] = mapped_column(DateTime, default=now)


class SolverRun(Base):
    __tablename__ = "solver_run"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    schuljahr_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schuljahr.id"))
    ziel_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("planversion.id"), nullable=True)
    ergebnis_version_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("planversion.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=SolverStatus.PENDING.value)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    zeitbudget_s: Mapped[int] = mapped_column(Integer, default=60)
    fixierungen: Mapped[list] = mapped_column(JSONB, default=list)  # Stunden-IDs: nicht verschieben
    teilloesung: Mapped[dict] = mapped_column(JSONB, default=dict)  # {"klassen": [...], "lehrkraefte": [...]}
    seed: Mapped[int] = mapped_column(Integer, default=0)
    ergebnis_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    fehler: Mapped[str | None] = mapped_column(Text, nullable=True)
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=now)
    gestartet_am: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    beendet_am: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Abwesenheit(Base):
    __tablename__ = "abwesenheit"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    lehrkraft_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("lehrkraft.id"), index=True)
    datum: Mapped[date] = mapped_column(Date, index=True)
    typ: Mapped[str] = mapped_column(String(20), default=AbwesenheitsTyp.KRANKHEIT.value)
    grund: Mapped[str | None] = mapped_column(Text, nullable=True)
    gemeldet_am: Mapped[datetime] = mapped_column(DateTime, default=now)
    gemeldet_von: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("benutzer.id"), nullable=True)


class Vertretung(Base):
    __tablename__ = "vertretung"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    stunde_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("stunde.id"), index=True)
    abwesenheit_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("abwesenheit.id"), nullable=True)
    typ: Mapped[str] = mapped_column(String(30), default=VertretungsTyp.FACHVERTRETUNG.value)
    vertreter_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("lehrkraft.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="vorschlag")  # vorschlag, angepasst, veroeffentlicht
    erstellt_am: Mapped[datetime] = mapped_column(DateTime, default=now)
    veroeffentlicht_am: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Pruefungstermin(Base):
    __tablename__ = "pruefungstermin"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    schuljahr_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schuljahr.id"))
    bezeichnung: Mapped[str] = mapped_column(String(200))
    art: Mapped[str] = mapped_column(String(50))  # testwoche, kolloquium, reifepruefung, standardueberpruefung
    datum: Mapped[date] = mapped_column(Date, index=True)
    von_slot: Mapped[int] = mapped_column(Integer)
    bis_slot: Mapped[int] = mapped_column(Integer)
    raum_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("raum.id"), nullable=True)
    pruefer_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("lehrkraft.id"), nullable=True)
    klasse_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("klasse.id"), nullable=True)
    kandidat: Mapped[str | None] = mapped_column(String(200), nullable=True)
    kollisionsfrei: Mapped[bool] = mapped_column(Boolean, default=True)


class Notification(Base):
    __tablename__ = "notification"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("benutzer.id"), index=True)
    typ: Mapped[str] = mapped_column(String(40))
    titel: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text, default="")
    gelesen: Mapped[bool] = mapped_column(Boolean, default=False)
    zeitpunkt: Mapped[datetime] = mapped_column(DateTime, default=now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("schule.id"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("benutzer.id"), nullable=True)
    aktion: Mapped[str] = mapped_column(String(60), index=True)
    objekt: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    zeitpunkt: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)


class AboToken(Base):
    __tablename__ = "abo_token"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    school_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("schule.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    art: Mapped[str] = mapped_column(String(20))  # klasse | lehrkraft
    ziel_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("benutzer.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
