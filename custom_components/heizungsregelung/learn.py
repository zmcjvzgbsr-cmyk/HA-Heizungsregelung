"""Lernendes Raummodell (ohne Home-Assistant-Abhängigkeiten, testbar).

Modell je Raum (Temperaturänderung in K/h):

    dT/dt = -a · (T_innen - T_außen) + b · H + c

- a: Wärmeverlust (1/h); 1/a ist die Zeitkonstante des Raums in Stunden
- b: Heizwirkung je Kelvin Antrieb bei voll offenem Ventil (1/h)
- c: sonstige Gewinne/Verluste (Sonne, Personen, Nachbarräume) in K/h
- H: wirksame Heizung = f(Ventilöffnung) · (Vorlauf - Raum), verzögert um die Trägheit
  des Heizkörpers (HEAT_LAG_MIN); ohne Vorlauffühler 30 K, solange der Kessel heizt

Geschätzt wird mit gewichteten kleinsten Quadraten über 60-Minuten-Fenster (bei groben
Sensoren 120 Minuten), die alle 15 Minuten gebildet werden. Ältere Fenster verblassen
langsam (Gedächtnis ≈ 10 Tage), eine schwache, nicht verblassende Vorannahme hält die
drei Werte auseinander. Ausreißer werden heruntergewichtet, Fenster mit offenem Fenster
oder schnell steigender Luftfeuchte (Duschen, Kochen) werden übersprungen.

Thermostatventile geben schon bei kleiner Öffnung viel Leistung ab. Deshalb rechnet das
Modell parallel mit drei Ventil-Kennlinien f(p) = 1 - (1 - p)^k und nimmt je Raum die,
die die Messungen am besten trifft.

Als „sicher“ gilt ein Raum, wenn seine Auskühl- und Aufheizrate genau genug vorhergesagt
werden – nicht, wenn jeder Einzelwert exakt bestimmt ist.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Any

MODEL_VERSION = 3
WINDOW_MIN = 60
WINDOW_COARSE_MIN = 120
STEP_MIN = 15
HEAT_LAG_MIN = 20.0
MEMORY_WINDOWS = 900  # ≈ 10 Tage bei einem Fenster je 15 Minuten
DECAY = 1.0 - 1.0 / MEMORY_WINDOWS
DEFAULT_DRIVE = 30.0
DEFAULT_VL_HEAT = 45.0
MIN_SAMPLES = 48
MIN_HEAT = 12
MIN_COOL = 12
MAX_GOOD_RMSE = 0.8  # K/h, darüber passt das Modell grundsätzlich nicht
SD_COOL_OK = 0.10  # K/h Unsicherheit der Auskühlrate
SD_HEAT_OK = 0.20  # K/h Unsicherheit der Aufheizrate
COARSE_STEP = 0.25  # K: kleinere Schritte nie gesehen -> grober Sensor
BOUNDS = ((0.003, 0.5), (0.0, 0.3), (-0.5, 0.5))
PRIOR = (0.02, 0.03, 0.0)
PRIOR_SD = (0.02, 0.03, 0.15)
HUBER_K = 2.5
# Ventil-Kennlinien: Name -> Exponent k in f(p) = 1 - (1 - p)^k
CURVES: dict[str, float] = {"linear": 1.0, "leicht": 2.0, "stark": 4.0}
CURVE_LABELS = {"linear": "linear", "leicht": "leicht gekrümmt", "stark": "stark gekrümmt"}
CURVE_SWITCH_MIN_N = 96
CURVE_SWITCH_MARGIN = 0.9
# Duschen/Kochen: Luftfeuchte steigt in 10 Minuten um mindestens 3 %-Punkte
HUM_RISE = 3.0
HUM_RISE_MIN = 10
HUM_HOLD_MIN = 45


@dataclass
class Sample:
    """Ein Messpunkt pro Minute."""

    tin: float | None
    tout: float | None
    u: float | None
    vl: float | None
    boiler_on: bool
    window_open: bool
    heat: dict[str, float] | None = None  # wirksame Heizung je Kennlinie, siehe apply_lag
    hum: float | None = None
    disturbed: bool = False  # Duschen/Kochen erkannt


def curve(p: float, k: float) -> float:
    """Ventil-Kennlinie: Anteil der Heizleistung bei Öffnung p (0…1)."""
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** k


def drive(s: Sample) -> float:
    """Heizantrieb in K für einen Messpunkt."""
    if s.vl is not None and s.tin is not None:
        return max(0.0, s.vl - s.tin)  # ruht der Kessel, kühlt das Rohr ab -> Antrieb fällt von selbst
    return DEFAULT_DRIVE if s.boiler_on else 0.0


LAG_ALPHA = 1.0 - math.exp(-1.0 / HEAT_LAG_MIN)


def lag_step(prev: dict[str, float] | None, s: Sample) -> dict[str, float] | None:
    """Wirksame Heizung je Kennlinie um eine Minute weiterrechnen (Trägheit des Heizkörpers)."""
    if s.u is None:
        return prev
    d = drive(s)
    raw = {name: curve(s.u, k) * d for name, k in CURVES.items()}
    if not isinstance(prev, dict) or set(prev) != set(raw):
        return raw
    return {name: prev[name] + (raw[name] - prev[name]) * LAG_ALPHA for name in raw}


def apply_lag(samples: list[Sample], start: dict[str, float] | None = None) -> dict[str, float] | None:
    """Wirksame Heizung für eine ganze Reihe berechnen; gibt den Endwert zurück."""
    h = start
    for s in samples:
        h = lag_step(h, s)
        s.heat = h
    return h


class HumidityWatch:
    """Erkennt Duschen/Kochen an schnell steigender Luftfeuchte und hält die Sperre eine Weile."""

    def __init__(self) -> None:
        self._hist: deque[float | None] = deque(maxlen=HUM_RISE_MIN + 1)
        self._hold = 0

    def step(self, hum: float | None) -> bool:
        self._hist.append(hum)
        if hum is not None:
            older = [h for h in list(self._hist)[:-1] if h is not None]
            if older and hum - min(older) >= HUM_RISE:
                self._hold = HUM_HOLD_MIN
        if self._hold > 0:
            self._hold -= 1
            return True
        return False


def mark_disturbances(samples: list[Sample]) -> int:
    """Duschen/Kochen in einer Minutenreihe markieren; gibt die Zahl gesperrter Minuten zurück."""
    watch = HumidityWatch()
    n = 0
    for s in samples:
        if watch.step(s.hum):
            s.disturbed = True
        if s.disturbed:
            n += 1
    return n


def min_step(samples: list[Sample]) -> float | None:
    """Kleinster Temperaturschritt eines Sensors (zur Erkennung grober Sensoren)."""
    q = None
    prev = None
    for s in samples:
        if s.tin is None:
            continue
        if prev is not None:
            d = abs(s.tin - prev)
            if d > 0.004 and (q is None or d < q):
                q = d
        prev = s.tin
    return q


def window_features(seg: list[Sample]) -> tuple[dict[str, list[float]], float, float] | None:
    """Merkmale und Messwert eines Fensters, oder None, wenn es unbrauchbar ist.

    Rückgabe: (x je Kennlinie, y, u_mittel) mit x = [-(Ti-Ta), H, 1], y = dT/dt in K/h.
    """
    n = len(seg)
    if n < 31:
        return None
    for s in seg:
        if (
            s.tin is None
            or s.tout is None
            or s.u is None
            or s.window_open
            or s.disturbed
            or not isinstance(s.heat, dict)
        ):
            return None
    # Steigung per linearer Regression über alle Punkte
    ts = [i / 60.0 for i in range(n)]
    tm = sum(ts) / n
    ym = sum(s.tin for s in seg) / n
    num = sum((t - tm) * (s.tin - ym) for t, s in zip(ts, seg, strict=True))
    den = sum((t - tm) ** 2 for t in ts)
    y = num / den
    dt_mean = sum(s.tin - s.tout for s in seg) / n
    u_mean = sum(s.u for s in seg) / n
    xs = {name: [-dt_mean, sum(s.heat[name] for s in seg) / n, 1.0] for name in CURVES}
    return xs, y, u_mean


def _inv(m: list[list[float]]) -> list[list[float]] | None:
    """Inverse einer kleinen quadratischen Matrix (Gauß-Jordan), None wenn (fast) singulär."""
    n = len(m)
    scale = max((abs(m[i][i]) for i in range(n)), default=0.0)
    if scale <= 0:
        return None
    a = [list(row) + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(m)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[piv][col]) < 1e-10 * scale:
            return None
        a[col], a[piv] = a[piv], a[col]
        p = a[col][col]
        a[col] = [v / p for v in a[col]]
        for r in range(n):
            if r != col and a[r][col] != 0.0:
                f = a[r][col]
                a[r] = [vr - f * vc for vr, vc in zip(a[r], a[col], strict=True)]
    return [row[n:] for row in a]


def _quad(x: list[float], cov: list[list[float]] | None) -> float:
    if cov is None:
        return float("inf")
    v = sum(x[i] * cov[i][j] * x[j] for i in range(3) for j in range(3))
    return math.sqrt(max(v, 0.0))


class _Fit:
    """Gewichtete kleinste Quadrate mit Verblassen und fester, schwacher Vorannahme (eine Kennlinie)."""

    def __init__(self, d: dict[str, Any] | None = None) -> None:
        d = d or {}
        self.S: list[list[float]] = d.get("S") or [[0.0] * 3 for _ in range(3)]
        self.r: list[float] = d.get("r") or [0.0] * 3
        self.n: int = int(d.get("n", 0))
        self.mse: float = float(d.get("mse", 0.04))
        self.theta: list[float] = list(d.get("theta") or PRIOR)
        self.cov: list[list[float]] | None = d.get("cov")

    def as_dict(self) -> dict[str, Any]:
        return {"S": self.S, "r": self.r, "n": self.n, "mse": self.mse, "theta": self.theta, "cov": self.cov}

    def predict(self, x: list[float]) -> float:
        return sum(t * xi for t, xi in zip(self.theta, x, strict=True))

    def _solve(self, overlap: float) -> None:
        m = max(self.mse, 0.02)
        ridge = [m / (sd * sd) for sd in PRIOR_SD]
        A = [[self.S[i][j] + (ridge[i] if i == j else 0.0) for j in range(3)] for i in range(3)]
        rhs = [self.r[i] + ridge[i] * PRIOR[i] for i in range(3)]
        inv = _inv(A)
        if inv is None:
            return
        th = [sum(inv[i][j] * rhs[j] for j in range(3)) for i in range(3)]
        self.theta = [min(max(v, lo), hi) for v, (lo, hi) in zip(th, BOUNDS, strict=True)]
        # Fenster überlappen sich (alle 15 min ein 60/120-min-Fenster): Fehler benachbarter
        # Fenster hängen zusammen, die Unsicherheit wird entsprechend größer angesetzt.
        self.cov = [[m * overlap * inv[i][j] for j in range(3)] for i in range(3)]

    def update(self, x: list[float], y: float, overlap: float) -> float:
        e = y - self.predict(x)
        sigma = max(math.sqrt(max(self.mse, 0.0)), 0.15)
        w = 1.0
        if self.n >= 10 and abs(e) > HUBER_K * sigma:
            w = HUBER_K * sigma / abs(e)  # Ausreißer (Baden, Tür offen, Sonne) zählen weniger
        for i in range(3):
            self.r[i] = DECAY * self.r[i] + w * x[i] * y
            for j in range(3):
                self.S[i][j] = DECAY * self.S[i][j] + w * x[i] * x[j]
        self.n += 1
        self.mse = 0.98 * self.mse + 0.02 * min(e * e, (4 * sigma) ** 2)
        self._solve(overlap)
        return e

    def sd_of(self, x: list[float]) -> float:
        """Unsicherheit einer Vorhersage x·θ (K/h)."""
        return _quad(x, self.cov)


class RoomLearner:
    """Raummodell mit automatischer Wahl der Ventil-Kennlinie."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        d = data or {}
        if d.get("version") != MODEL_VERSION:
            d = {}
        fits = d.get("fits") or {}
        self.fits: dict[str, _Fit] = {name: _Fit(fits.get(name)) for name in CURVES}
        self.active: str = d.get("active") if d.get("active") in CURVES else "linear"
        self.n: int = int(d.get("n", 0))
        self.n_heat: int = int(d.get("n_heat", 0))
        self.n_cool: int = int(d.get("n_cool", 0))
        self.n_disturbed: int = int(d.get("n_disturbed", 0))
        self.vl_heat: float = float(d.get("vl_heat", DEFAULT_VL_HEAT))
        self.dt_avg: float | None = d.get("dt_avg")
        self.q: float | None = d.get("q")

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": MODEL_VERSION,
            "fits": {k: f.as_dict() for k, f in self.fits.items()},
            "active": self.active,
            "n": self.n,
            "n_heat": self.n_heat,
            "n_cool": self.n_cool,
            "n_disturbed": self.n_disturbed,
            "vl_heat": self.vl_heat,
            "dt_avg": self.dt_avg,
            "q": self.q,
        }

    @property
    def fit(self) -> _Fit:
        return self.fits[self.active]

    @property
    def theta(self) -> list[float]:
        return self.fit.theta

    @property
    def mse(self) -> float:
        return self.fit.mse


    @property
    def window_min(self) -> int:
        """Fensterlänge: bei groben Sensoren länger, damit Stufen nicht als Sprünge zählen."""
        return WINDOW_COARSE_MIN if (self.q is not None and self.q >= COARSE_STEP) else WINDOW_MIN

    def note_step(self, q: float | None) -> None:
        if q is not None and (self.q is None or q < self.q):
            self.q = q

    # ---------------------------------------------------------------- Lernen
    def update(self, xs: dict[str, list[float]], y: float, u_mean: float) -> float:
        """Ein Fenster einlernen, gibt den Vorhersagefehler (K/h) der aktiven Kennlinie zurück."""
        overlap = self.window_min / STEP_MIN
        errs = {name: self.fits[name].update(xs[name], y, overlap) for name in CURVES}
        self.n += 1
        if u_mean >= 0.3:
            self.n_heat += 1
        elif u_mean <= 0.05:
            self.n_cool += 1
        dt = -xs["linear"][0]  # Ti - Ta; Referenz für die Unsicherheit merken
        self.dt_avg = dt if self.dt_avg is None else 0.99 * self.dt_avg + 0.01 * dt
        if self.n >= CURVE_SWITCH_MIN_N:
            best = min(CURVES, key=lambda k: self.fits[k].mse)
            if best != self.active and self.fits[best].mse < CURVE_SWITCH_MARGIN * self.fit.mse:
                self.active = best
        return errs[self.active]

    def note_vl(self, vl: float | None, boiler_on: bool) -> None:
        """Typische Vorlauftemperatur beim Heizen mitlernen."""
        if vl is not None and boiler_on and 25 <= vl <= 80:
            self.vl_heat = 0.995 * self.vl_heat + 0.005 * vl

    def learn_series(self, samples: list[Sample]) -> int:
        """Eine Minutenreihe einlernen (Start aus dem Verlauf). Setzt die verzögerte Heizung selbst."""
        self.note_step(min_step(samples))
        apply_lag(samples)
        mark_disturbances(samples)
        for s in samples:
            self.note_vl(s.vl, s.boiler_on)
        w = self.window_min
        used = 0
        for start in range(0, len(samples) - w, STEP_MIN):
            seg = samples[start : start + w + 1]
            f = window_features(seg)
            if f is None:
                if any(s.disturbed for s in seg):
                    self.n_disturbed += 1
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

    @property
    def dt_ref(self) -> float:
        """Typischer Abstand Innen–Außen der gelernten Fenster (K)."""
        return self.dt_avg if self.dt_avg is not None else 15.0

    @property
    def sd_cool(self) -> float:
        """Unsicherheit der Auskühlrate beim typischen Abstand Innen–Außen (K/h)."""
        return self.fit.sd_of([-self.dt_ref, 0.0, 1.0])

    @property
    def sd_heat(self) -> float:
        """Unsicherheit der Aufheizrate bei offenem Ventil und typischem Vorlauf (K/h)."""
        return self.fit.sd_of([-self.dt_ref, max(0.0, self.vl_heat - 19.0), 1.0])

    @property
    def progress(self) -> int:
        """Lernstand in Prozent: genug Fenster, Vorhersagen sicher, Fehler klein."""
        sc, sh = self.sd_cool, self.sd_heat
        conf = min(1.0, SD_COOL_OK / sc if sc > 0 else 1.0, SD_HEAT_OK / sh if sh > 0 else 1.0)
        parts = (
            min(1.0, self.n / MIN_SAMPLES),
            min(1.0, self.n_heat / MIN_HEAT),
            min(1.0, self.n_cool / MIN_COOL),
            conf,
            min(1.0, MAX_GOOD_RMSE / max(self.rmse, 1e-6)),
        )
        return round(100 * min(parts))

    @property
    def limit_reason(self) -> str | None:
        """Was den Lernstand gerade begrenzt (für die Anzeige)."""
        if self.reliable:
            return None
        sc, sh = self.sd_cool, self.sd_heat
        parts = {
            "zu wenige Lernfenster": self.n / MIN_SAMPLES,
            "zu wenige Heizphasen": self.n_heat / MIN_HEAT,
            "zu wenige Auskühlphasen": self.n_cool / MIN_COOL,
            "Auskühlrate noch unsicher": SD_COOL_OK / sc if sc > 0 else 1.0,
            "Aufheizrate noch unsicher": SD_HEAT_OK / sh if sh > 0 else 1.0,
            "Modellfehler zu groß": MAX_GOOD_RMSE / max(self.rmse, 1e-6),
        }
        return min(parts, key=parts.get)

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
        """Erwärmung bei voll offenem Ventil und heizendem Kessel in K/h (eingeschwungen)."""
        d = max(0.0, (vl if vl is not None else self.vl_heat) - tin) if has_vl else DEFAULT_DRIVE
        return self.b * d - self.a * (tin - tout) + self.c

    def minutes_to_target(
        self, tin: float, target: float, tout: float, vl: float | None = None, has_vl: bool = True
    ) -> float | None:
        """Minuten bis zur Zieltemperatur bei voller Heizleistung (None = nicht erreichbar)."""
        if tin >= target - 0.05:
            return 0.0
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
