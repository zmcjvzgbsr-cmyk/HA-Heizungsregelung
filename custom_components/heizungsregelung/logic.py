"""Reine Regel-Logik ohne Home-Assistant-Abhängigkeiten (testbar)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass
class RoomInput:
    """Momentaufnahme eines Raums für die Bedarfsberechnung."""

    name: str
    target: float | None
    current: float | None
    heating_allowed: bool = True  # hvac_mode != off
    window_open: bool = False
    window_closed_seconds: float | None = None  # seit wann wieder zu


@dataclass
class BedarfResult:
    """Ergebnis der Heizbedarfs-Berechnung."""

    value: float
    leading_room: str | None
    deficits: dict[str, float]


def room_deficit(
    room: RoomInput, lueften_grenze: float, nachlauf_seconds: float
) -> float | None:
    """Unterdeckung eines Raums in K (Ziel minus Ist) oder None, wenn er nicht zählt.

    - Fenster offen: Raum zählt nicht (Better Thermostat schließt dann ohnehin).
    - Fenster erst kürzlich geschlossen: Bedarf wird auf die Lüften-Grenze begrenzt,
      damit kurzes Lüften keinen großen Kessel-Schub auslöst.
    """
    if not room.heating_allowed or room.window_open:
        return None
    if room.target is None or room.current is None:
        return None
    diff = room.target - room.current
    if room.window_closed_seconds is not None and room.window_closed_seconds < nachlauf_seconds:
        diff = min(diff, lueften_grenze)
    return diff


def heizbedarf(
    rooms: list[RoomInput], lueften_grenze: float, nachlauf_seconds: float, clamp: float = 2.0
) -> BedarfResult:
    """Größte Unterdeckung aller Räume, begrenzt auf ±clamp."""
    deficits: dict[str, float] = {}
    for room in rooms:
        d = room_deficit(room, lueften_grenze, nachlauf_seconds)
        if d is not None:
            deficits[room.name] = round(d, 2)
    if not deficits:
        return BedarfResult(-clamp, None, deficits)
    leading = max(deficits, key=lambda k: deficits[k])
    value = max(-clamp, min(clamp, deficits[leading]))
    return BedarfResult(round(value, 1), leading, deficits)


@dataclass
class BoilerParams:
    """Parameter der Kesselregelung."""

    schub_faktor: float
    schub_maximum: float
    ruhe_sollwert: float
    start_schwelle: float
    stopp_schwelle: float
    mindestpause_s: float
    sollwert_min: float
    sollwert_max: float


@dataclass
class BoilerDecision:
    """Entscheidung der Kesselregelung."""

    heizen: bool
    sollwert: float
    wechsel: bool
    schreiben: bool
    grund: str


def round_half(value: float) -> float:
    """Auf 0,5 runden."""
    return round(value * 2) / 2


def boiler_decision(
    *,
    bedarf: float,
    basis: float,
    aktuell: float | None,
    heizt: bool,
    seit_modus_s: float,
    seit_aenderung_s: float,
    p: BoilerParams,
    immediate_delta: float = 2.0,
    delayed_delta: float = 1.0,
    delay_s: float = 900,
) -> BoilerDecision:
    """Kessel-Sollwert berechnen (Logik der bisherigen Automation).

    - Heizen mit Hysterese: an ab Start-Schwelle (nach Mindestpause, außer Bedarf >= 1 K),
      aus wenn Bedarf <= Stopp-Schwelle.
    - Heizen: Sollwert = Basis (Raumtemperatur des Kessels) + min(Faktor x Bedarf, Maximum).
    - Ruhe: Sollwert = Ruhe-Sollwert.
    - Geschrieben wird bei Moduswechsel, bei >= 2 K Abweichung sofort,
      bei >= 1 K nach 15 min seit der letzten Änderung.
    """
    if heizt:
        heizen = bedarf > p.stopp_schwelle
    else:
        heizen = bedarf >= p.start_schwelle and (
            seit_modus_s >= p.mindestpause_s or bedarf >= 1.0
        )
    if heizen:
        wert = basis + min(p.schub_faktor * bedarf, p.schub_maximum)
    else:
        wert = p.ruhe_sollwert
    wert = round_half(max(p.sollwert_min, min(p.sollwert_max, wert)))
    wechsel = heizen != heizt
    if aktuell is None:
        return BoilerDecision(heizen, wert, wechsel, True, "kein aktueller Sollwert")
    d = abs(wert - aktuell)
    if wechsel and d > 0:
        return BoilerDecision(heizen, wert, wechsel, True, "Moduswechsel")
    if d >= immediate_delta:
        return BoilerDecision(heizen, wert, wechsel, True, f"Abweichung {d:.1f} K")
    if d >= delayed_delta and seit_aenderung_s >= delay_s:
        return BoilerDecision(heizen, wert, wechsel, True, f"Abweichung {d:.1f} K nach Wartezeit")
    return BoilerDecision(heizen, wert, wechsel, False, "keine Änderung nötig")


def parse_time(value: str | time | None) -> time | None:
    """'HH:MM' oder 'HH:MM:SS' in time umwandeln."""
    if value is None or value == "":
        return None
    if isinstance(value, time):
        return value
    parts = [int(x) for x in str(value).split(":")]
    while len(parts) < 3:
        parts.append(0)
    return time(parts[0], parts[1], parts[2])


def in_window(now: datetime, start: time, end: time) -> bool:
    """Liegt die Uhrzeit von now im Fenster [start, end)? Über Mitternacht erlaubt."""
    t = now.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def away_exception_active(
    now: datetime, start: time | None, end: time | None, end_friday: time | None
) -> bool:
    """Ausnahme bei Abwesenheit aktiv (z. B. Kinderzimmer nachmittags)?"""
    if start is None or end is None:
        return False
    effective_end = end_friday if (now.weekday() == 4 and end_friday) else end
    return in_window(now, start, effective_end)


def next_rhythm_start(now: datetime, weekday: int, start: time) -> datetime:
    """Nächster Termin am Wochentag (0=Mo) zur Uhrzeit, der noch nicht begonnen hat."""
    days = (weekday - now.weekday()) % 7
    cand = (now + timedelta(days=days)).replace(
        hour=start.hour, minute=start.minute, second=0, microsecond=0
    )
    if cand <= now:
        cand += timedelta(days=7)
    return cand


def advance_period(
    von: datetime, bis: datetime, now: datetime, interval_days: int
) -> tuple[datetime, datetime]:
    """Zeitraum so oft um das Intervall verschieben, bis das Ende in der Zukunft liegt."""
    step = timedelta(days=max(1, interval_days))
    for _ in range(1000):
        if bis > now:
            break
        von += step
        bis += step
    return von, bis


def capped(target: float, max_temp: float | None) -> float:
    """Zieltemperatur auf Raum-Maximum begrenzen."""
    if max_temp is None:
        return target
    return min(target, max_temp)
