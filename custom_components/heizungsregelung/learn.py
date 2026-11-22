"""Lernendes Raummodell (ohne Home-Assistant-Abhängigkeiten, testbar).

Modell je Raum (Temperaturänderung in K/h):

    dT/dt = -a · (T_innen - T_außen) + b · u · Antrieb + c

- a: Wärmeverlust (1/h); 1/a ist die Zeitkonstante des Raums in Stunden
- b: Heizwirkung je Kelvin Antrieb bei voll offenem Ventil (1/h)
- c: sonstige Gewinne/Verluste (Sonne, Personen, Nachbarräume) in K/h
- u: Ventilöffnung 0..1 (oder 0/1, wenn nur „heizt“ bekannt ist)
- Antrieb: Vorlauf - Raumtemperatur (K); ohne Vorlauffühler 30 K, solange der Kessel heizt

Geschätzt wird mit rekursiven kleinsten Quadraten (RLS) mit Vergessensfaktor,
aus 30-Minuten-Fenstern, die alle 10 Minuten gebildet werden.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

WINDOW_MIN = 30
STEP_MIN = 10
LAMBDA = 0.998  # wirksames Gedächtnis ~ 500 Fenster ≈ 3,5 Tage
DEFAULT_DRIVE = 30.0
DEFAULT_VL_HEAT = 45.0
MIN_SAMPLES = 36
MIN_HEAT = 6
BOUNDS = ((0.005, 1.0), (0.0, 0.5), (-1.5, 1.5))
PRIOR = (0.06, 0.02, 0.0)
P0 = (0.05, 0.005, 1.0)


@dataclass
class Sample:
    """Ein Messpunkt pro Minute."""

    tin: float | None
    tout: float | None
    u: float | None
    vl: float | None
    boiler_on: bool
    window_open: bool


def drive(s: Sample) -> float:
    """Heizantrieb in K für einen Messpunkt."""
    if s.vl is not None and s.tin is not None:
        return max(0.0, s.vl - s.tin)  # ruht der Kessel, kühlt das Rohr ab -> Antrieb fällt von selbst
    return DEFAULT_DRIVE if s.boiler_on else 0.0


def window_features(seg: list[Sample]) -> tuple[list[float], float, float] | None:
    """Merkmale und Messwert eines Fensters, oder None, wenn es unbrauchbar ist.

    Rückgabe: (x, y, u_mittel) mit x = [-(Ti-Ta), u·Antrieb, 1], y = dT/dt in K/h.
    """
    if len(seg) < WINDOW_MIN + 1:
        return None
    for s in seg:
        if s.tin is None or s.tout is None or s.u is None or s.window_open:
            return None
    hours = (len(seg) - 1) / 60.0
    # Steigung per linearer Regression über alle Punkte (robuster als Endpunkte)
    n = len(seg)
    ts = [i / 60.0 for i in range(n)]
    tm = sum(ts) / n
    ym = sum(s.tin for s in seg) / n
    num = sum((t - tm) * (s.tin - ym) for t, s in zip(ts, seg, strict=True))
    den = sum((t - tm) ** 2 for t in ts)
    y = num / den if den else (seg[-1].tin - seg[0].tin) / hours
    dt_mean = sum(s.tin - s.tout for s in seg) / n
    ud = sum(s.u * drive(s) for s in seg) / n
    u_mean = sum(s.u for s in seg) / n
    return [-dt_mean, ud, 1.0], y, u_mean


class RoomLearner:
    """RLS-Schätzer für ein Raummodell."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        d = data or {}
        self.theta: list[float] = list(d.get("theta") or PRIOR)
        self.P: list[list[float]] = d.get("P") or [
            [P0[0], 0.0, 0.0],
            [0.0, P0[1], 0.0],
            [0.0, 0.0, P0[2]],
        ]
        self.n: int = int(d.get("n", 0))
        self.n_heat: int = int(d.get("n_heat", 0))
        self.n_cool: int = int(d.get("n_cool", 0))
        self.mse: float = float(d.get("mse", 0.04))
        self.vl_heat: float = float(d.get("vl_heat", DEFAULT_VL_HEAT))

    def as_dict(self) -> dict[str, Any]:
        return {
            "theta": self.theta,
            "P": self.P,
            "n": self.n,
            "n_heat": self.n_heat,
            "n_cool": self.n_cool,
            "mse": self.mse,
            "vl_heat": self.vl_heat,
        }

    # ---------------------------------------------------------------- Lernen
    def update(self, x: list[float], y: float, u_mean: float) -> float:
        """Ein Fenster einlernen, gibt den Vorhersagefehler (K/h) zurück."""
        th, P = self.theta, self.P
        pred = sum(t * xi for t, xi in zip(th, x, strict=True))
        e = y - pred
        # Ausreißer (z. B. Tür offen, Duschen) dämpfen
        sigma = math.sqrt(max(self.mse, 1e-4))
        if abs(e) > 4 * sigma and self.n > MIN_SAMPLES:
            e = math.copysign(4 * sigma, e)
        Px = [sum(P[i][j] * x[j] for j in range(3)) for i in range(3)]
        denom = LAMBDA + sum(x[i] * Px[i] for i in range(3))
        k = [v / denom for v in Px]
        self.theta = [th[i] + k[i] * e for i in range(3)]
        self.P = [[(P[i][j] - k[i] * Px[j]) / LAMBDA for j in range(3)] for i in range(3)]
        # Kovarianz begrenzen (numerische Stabilität bei wenig Anregung)
        for i in range(3):
            self.P[i][i] = min(self.P[i][i], P0[i] * 4)
        self.theta = [min(max(v, lo), hi) for v, (lo, hi) in zip(self.theta, BOUNDS, strict=True)]
        self.n += 1
        if u_mean >= 0.3:
            self.n_heat += 1
        elif u_mean <= 0.05:
            self.n_cool += 1
        self.mse = 0.98 * self.mse + 0.02 * e * e
        return e

    def note_vl(self, vl: float | None, boiler_on: bool) -> None:
        """Typische Vorlauftemperatur beim Heizen mitlernen."""
        if vl is not None and boiler_on and 25 <= vl <= 80:
            self.vl_heat = 0.995 * self.vl_heat + 0.005 * vl

    def learn_series(self, samples: list[Sample]) -> int:
        """Eine Minutenreihe in Fenstern einlernen (für den Start aus dem Verlauf)."""
        used = 0
        for s in samples:
            self.note_vl(s.vl, s.boiler_on)
        for start in range(0, len(samples) - WINDOW_MIN, STEP_MIN):
            f = window_features(samples[start : start + WINDOW_MIN + 1])
            if f is None:
                continue
            self.update(*f)
            used += 1
        return used

    # ---------------------------------------------------------------- Ergebnisse
    @property
    def a(self) -> float:
        return self.theta[0]

    @property
    def b(self) -> float:
        return self.theta[1]

    @property
    def c(self) -> float:
        return self.theta[2]

    def sd(self, i: int) -> float:
        """Standardabweichung des Parameters i (aus RLS-Kovarianz und Restfehler)."""
        return math.sqrt(max(self.P[i][i], 0.0) * max(self.mse, 1e-4))

    @property
    def progress(self) -> int:
        """Lernstand in Prozent: genug Fenster, genug Heizphasen, Wärmeverlust sicher bestimmt."""
        sd_a = self.sd(0)
        conf = 1.0 if sd_a <= 0 else min(1.0, max(0.25 * self.a, 0.01) / sd_a)
        parts = (
            min(1.0, self.n / MIN_SAMPLES),
            min(1.0, self.n_heat / MIN_HEAT),
            conf,
        )
        return round(100 * min(parts))

    @property
    def reliable(self) -> bool:
        return self.progress >= 100

    @property
    def rmse(self) -> float:
        return math.sqrt(max(self.mse, 0.0))

    def cool_rate(self, tin: float, tout: float) -> float:
        """Auskühlung ohne Heizung in K/h (positiv = wird kälter)."""
        return self.a * (tin - tout) - self.c

    def heat_rate(self, tin: float, tout: float, vl: float | None = None, has_vl: bool = True) -> float:
        """Erwärmung bei voll offenem Ventil und heizendem Kessel in K/h."""
        d = max(0.0, (vl if vl is not None else self.vl_heat) - tin) if has_vl else DEFAULT_DRIVE
        return self.b * d - self.a * (tin - tout) + self.c

    def minutes_to_target(
        self, tin: float, target: float, tout: float, vl: float | None = None, has_vl: bool = True
    ) -> float | None:
        """Minuten bis zur Zieltemperatur bei voller Heizleistung (None = nicht erreichbar)."""
        if tin >= target - 0.05:
            return 0.0
        # Schrittweise rechnen, weil die Verluste mit steigender Temperatur wachsen
        t, minutes = tin, 0
        while t < target - 0.05:
            r = self.heat_rate(t, tout, vl, has_vl)
            if r <= 0.02:
                return None
            t += r / 60.0
            minutes += 1
            if minutes > 24 * 60:
                return None
        return float(minutes)
