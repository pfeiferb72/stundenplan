from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class DevLogin(BaseModel):
    email: str


class SchuleIn(BaseModel):
    name: str
    schulart: str = "MS"
    config: dict = Field(default_factory=dict)


class SchuleOut(BaseModel):
    id: int
    name: str
    schulart: str
    config: dict
    model_config = {"from_attributes": True}


class SchuljahrIn(BaseModel):
    bezeichnung: str
    start: date
    ende: date


class SchuljahrOut(BaseModel):
    id: int
    bezeichnung: str
    start: date
    ende: date
    aktiv: bool
    model_config = {"from_attributes": True}


class SemesterIn(BaseModel):
    schuljahr_id: int
    bezeichnung: str
    start: date
    ende: date


class SemesterOut(BaseModel):
    id: int
    bezeichnung: str
    start: date
    ende: date
    model_config = {"from_attributes": True}


class KlasseIn(BaseModel):
    schuljahr_id: int
    name: str
    jahrgang: int
    schuelerzahl: int = 25
    stammraum_id: int | None = None
    teilungsgruppe: str | None = None


class KlasseOut(BaseModel):
    id: int
    name: str
    jahrgang: int
    schuelerzahl: int
    stammraum_id: int | None
    teilungsgruppe: str | None
    model_config = {"from_attributes": True}


class GegenstandIn(BaseModel):
    code: str
    name: str
    schulart: str = "MS"
    benoetigt_fachraum: bool = False
    benoetigte_ausstattung: list[str] = Field(default_factory=list)


class GegenstandOut(BaseModel):
    id: int
    code: str
    name: str
    schulart: str
    benoetigt_fachraum: bool
    benoetigte_ausstattung: list
    model_config = {"from_attributes": True}


class LehrkraftIn(BaseModel):
    vorname: str
    nachname: str
    email: str
    lehrverpflichtung: float = 20.0
    max_tagesstunden: int = 8
    qualifikationen: list[str] = Field(default_factory=list)
    sperrzeiten: dict = Field(default_factory=dict)
    wunschfenster: dict = Field(default_factory=dict)
    unterrichtsfreie_tage: list[int] = Field(default_factory=list)


class LehrkraftOut(BaseModel):
    id: int
    vorname: str
    nachname: str
    email: str
    lehrverpflichtung: float
    max_tagesstunden: int
    qualifikationen: list
    sperrzeiten: dict
    wunschfenster: dict
    unterrichtsfreie_tage: list
    aktiv: bool
    model_config = {"from_attributes": True}


class RaumIn(BaseModel):
    name: str
    kapazitaet: int = 30
    ausstattung: list[str] = Field(default_factory=list)
    fachraum: bool = False
    ressourcenpool_id: int | None = None
    gesperrt_bis: date | None = None


class RaumOut(BaseModel):
    id: int
    name: str
    kapazitaet: int
    ausstattung: list
    fachraum: bool
    ressourcenpool_id: int | None
    gesperrt_bis: date | None
    model_config = {"from_attributes": True}


class StundentafelIn(BaseModel):
    schulart: str
    jahrgang: int
    gegenstand_id: int
    wochenstunden: int
    aufteilung: str = "1+1"
    rhythmus: str = "AB"


class StundentafelOut(BaseModel):
    id: int
    schulart: str
    jahrgang: int
    gegenstand_id: int
    wochenstunden: int
    aufteilung: str
    rhythmus: str
    model_config = {"from_attributes": True}


class VeranstaltungIn(BaseModel):
    schuljahr_id: int
    klasse_id: int
    gegenstand_id: int
    wochenstunden: int
    aufteilung: str = "1+1"
    rhythmus: str = "AB"
    teilung_nr: int = 0
    kopplungsgruppe: str | None = None
    lehrkraft_id: int | None = None
    fixiert: bool = False


class VeranstaltungOut(BaseModel):
    id: int
    schuljahr_id: int
    klasse_id: int
    gegenstand_id: int
    wochenstunden: int
    aufteilung: str
    rhythmus: str
    teilung_nr: int
    kopplungsgruppe: str | None
    lehrkraft_id: int | None
    fixiert: bool
    model_config = {"from_attributes": True}


class PlanversionIn(BaseModel):
    schuljahr_id: int
    name: str
    basis_version_id: int | None = None


class PlanversionOut(BaseModel):
    id: int
    schuljahr_id: int
    name: str
    status: str
    score: float
    basis_version_id: int | None
    created_by: int | None
    veroeffentlicht_at: datetime | None
    created_at: datetime
    model_config = {"from_attributes": True}


class StundeIn(BaseModel):
    veranstaltung_id: int
    wochentag: int = Field(ge=0, le=6)
    slot: int = Field(ge=0)
    laenge: int = Field(default=1, ge=1, le=4)
    raum_id: int
    lehrkraft_id: int
    zustand: str = "geplant"
    fixiert: bool = False


class StundeMoveIn(BaseModel):
    wochentag: int | None = None
    slot: int | None = None
    raum_id: int | None = None
    lehrkraft_id: int | None = None
    fixiert: bool | None = None


class StundeOut(BaseModel):
    id: int
    planversion_id: int
    veranstaltung_id: int
    wochentag: int
    slot: int
    laenge: int
    raum_id: int
    lehrkraft_id: int
    zustand: str
    vertretung_id: int | None
    fixiert: bool
    model_config = {"from_attributes": True}


class SolverRunIn(BaseModel):
    schuljahr_id: int
    ziel_version_id: int | None = None  # Reparaturmodus: bestehende Version optimieren
    zeitbudget_s: int = Field(default=60, ge=5, le=900)
    fixierungen: list[int] = Field(default_factory=list)
    teilloesung: dict = Field(default_factory=dict)
    seed: int = 0


class SolverRunOut(BaseModel):
    id: int
    schuljahr_id: int
    ziel_version_id: int | None
    ergebnis_version_id: int | None
    status: str
    progress: float
    zeitbudget_s: int
    ergebnis_score: float | None
    fehler: str | None
    erstellt_am: datetime
    beendet_am: datetime | None
    model_config = {"from_attributes": True}


class AbwesenheitIn(BaseModel):
    lehrkraft_id: int
    datum: date
    typ: str = "krankheit"
    grund: str | None = None


class AbwesenheitOut(BaseModel):
    id: int
    lehrkraft_id: int
    datum: date
    typ: str
    grund: str | None
    gemeldet_am: datetime
    model_config = {"from_attributes": True}


class VertretungIn(BaseModel):
    stunde_id: int
    abwesenheit_id: int | None = None
    typ: str = "fachvertretung"
    vertreter_id: int | None = None


class VertretungPatch(BaseModel):
    typ: str | None = None
    vertreter_id: int | None = None
    status: str | None = None


class VertretungOut(BaseModel):
    id: int
    stunde_id: int
    abwesenheit_id: int | None
    typ: str
    vertreter_id: int | None
    status: str
    erstellt_am: datetime
    veroeffentlicht_am: datetime | None
    model_config = {"from_attributes": True}


class PruefungIn(BaseModel):
    schuljahr_id: int
    bezeichnung: str
    art: str
    datum: date
    von_slot: int
    bis_slot: int
    raum_id: int | None = None
    pruefer_id: int | None = None
    klasse_id: int | None = None
    kandidat: str | None = None


class PruefungOut(BaseModel):
    id: int
    bezeichnung: str
    art: str
    datum: date
    von_slot: int
    bis_slot: int
    raum_id: int | None
    pruefer_id: int | None
    klasse_id: int | None
    kandidat: str | None
    kollisionsfrei: bool
    model_config = {"from_attributes": True}


class UserIn(BaseModel):
    email: str
    name: str
    role: str
    school_id: int | None = None
    lehrkraft_id: int | None = None
    klasse_id: int | None = None


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    school_id: int | None
    lehrkraft_id: int | None
    klasse_id: int | None
    aktiv: bool
    model_config = {"from_attributes": True}


class ConfigPatch(BaseModel):
    config: dict[str, Any]


class ValidateOut(BaseModel):
    harte_verletzungen: list[dict]
    weiche_verletzungen: list[dict]
    score: float


class ScoreOut(BaseModel):
    score: float
    harte_verletzungen: int
    weiche_verletzungen: list[dict]
