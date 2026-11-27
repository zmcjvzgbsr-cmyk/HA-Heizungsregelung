"""Tests des lernenden Raummodells mit simulierten Räumen (inkl. realer Störungen)."""

import math
import random

import pytest

from custom_components.heizungsregelung.learn import (
    HumidityWatch,
    RoomLearner,
    Sample,
    curve,
    mark_disturbances,
)


def simulate(
    a, b, c=0.0, days=7, seed=1, vl_sensor=True, quant=0.01, lag_min=20.0,
    bathing=False, doors=False, sun=0.0, tout_mean=5.0, tout_amp=3.0, bang_bang=False,
    valve_k=1.0, noise=0.0, humidity=True,
):
    """Raum mit bekannten Werten simulieren (Minutentakt).

    valve_k: wahre Ventil-Kennlinie (1 = linear, 4 = Thermostatventil, öffnet früh)
    noise: langsame, unerkannte Störungen (Personen, Türen, Nachbarräume) in K/h
    """
    rnd = random.Random(seed)
    tin, heat_eff, samples = 19.0, 0.0, []
    alpha = 1 - math.exp(-1 / lag_min)
    spike = 0.0
    hum_spike = 0.0
    slow = 0.0
    u = 0.0
    for m in range(days * 24 * 60):
        h = (m / 60) % 24
        day = m // 1440
        tout = tout_mean + tout_amp * math.sin((h - 9) / 24 * 2 * math.pi) + 2 * math.sin(day / 3)
        target = 20.0 if 5 <= h < 22 else 17.5
        if bang_bang:  # Thermostat: auf/zu mit Totband
            if tin < target - 0.3:
                u = 1.0
            elif tin > target + 0.1:
                u = 0.0
        else:  # Better Thermostat: moduliert, oft nur wenige Prozent offen
            u = max(0.0, min(1.0, (target - tin) * (0.8 if valve_k > 1 else 2.5)))
        boiler_on = u > 0.05
        vl = 44 + 6 * u if boiler_on else max(tin + 2, 25)
        d = (vl - tin) if vl_sensor else (30 if boiler_on else 0)
        heat_eff += (curve(u, valve_k) * max(0, d) - heat_eff) * alpha
        gain = c + sun * max(0.0, math.sin((h - 9) / 8 * math.pi)) if 9 <= h <= 17 else c
        slow += (rnd.gauss(0, noise) - slow) / 30 if noise else 0.0
        rate = -a * (tin - tout) + b * heat_eff + gain + slow * 4 + rnd.gauss(0, 0.05)
        tin += rate / 60
        win = (m % 1440) in range(7 * 60, 7 * 60 + 10)  # täglich 10 min lüften (mit Sensor)
        if win:
            tin -= 0.06
        if bathing and (m % 1440) == 19 * 60 and rnd.random() < 0.6:
            spike = 2.5  # Baden/Duschen: +2,5 K Dampf/Wärme, klingt ab (kein Fenstersensor)
            hum_spike = 25.0
        if doors and rnd.random() < 0.002:
            tin -= 0.4  # Tür offen, Kaltluft (unerkannt)
        spike *= math.exp(-1 / 40)
        hum_spike *= math.exp(-1 / 50)
        meas = round((tin + spike) / quant) * quant
        hum = round(55 + hum_spike + rnd.gauss(0, 0.3), 1) if humidity else None
        samples.append(
            Sample(
                meas, round(tout, 1), round(u, 2), round(vl, 1) if vl_sensor else None, boiler_on, win,
                hum=hum,
            )
        )
    return samples


def check(lr, a, b, c=0.0, tol_cool=0.12, tol_heat=0.2):
    cool_true = a * (20 - 5) - c
    heat_true = b * (45 - 19) - a * (19 - 5) + c
    assert lr.cool_rate(20, 5) == pytest.approx(cool_true, abs=tol_cool), (lr.theta, lr.rmse)
    assert lr.heat_rate(19, 5, 45) == pytest.approx(heat_true, abs=tol_heat), (lr.theta, lr.rmse)


@pytest.mark.parametrize("a,b,c", [(0.02, 0.035, 0.0), (0.035, 0.05, 0.1), (0.015, 0.025, -0.05)])
def test_recovers_rates(a, b, c):
    lr = RoomLearner()
    assert lr.learn_series(simulate(a, b, c)) > 300
    assert lr.reliable
    check(lr, a, b, c)


def test_coarse_sensor_bang_bang():
    """Wohnzimmer-Fall: Sensor in 0,5-K-Schritten, Ventil auf/zu."""
    lr = RoomLearner()
    lr.learn_series(simulate(0.02, 0.035, quant=0.5, bang_bang=True))
    assert lr.window_min == 120
    check(lr, 0.02, 0.035, tol_cool=0.15, tol_heat=0.3)


def test_bathroom_shower_is_skipped():
    """Bad: Duschen hebt Temperatur und Luftfeuchte – die Fenster werden übersprungen."""
    samples = simulate(0.025, 0.04, bathing=True, doors=True, sun=0.2, seed=3)
    lr = RoomLearner()
    lr.learn_series(samples)
    assert lr.n_disturbed > 5
    assert lr.cool_rate(20, 5) == pytest.approx(0.025 * 15, abs=0.12), (lr.theta, lr.rmse)
    assert lr.heat_rate(19, 5, 45) > 0.3
    assert lr.reliable, lr.limit_reason

    blind = RoomLearner()
    blind.learn_series(simulate(0.025, 0.04, bathing=True, doors=True, sun=0.2, seed=3, humidity=False))
    assert blind.rmse > lr.rmse


@pytest.mark.parametrize("valve_k", [2.0, 4.0])
def test_thermostat_valve_curve(valve_k):
    """Kinderzimmer-Fall: Ventil meist nur 10–30 % offen, gibt aber viel mehr Leistung ab."""
    lr = RoomLearner()
    lr.learn_series(simulate(0.025, 0.03, valve_k=valve_k, seed=5))
    assert lr.active != "linear"
    assert lr.fits[lr.active].mse < lr.fits["linear"].mse
    check(lr, 0.025, 0.03, tol_cool=0.12, tol_heat=0.25)
    assert lr.reliable, lr.limit_reason


def test_noisy_room_still_finishes():
    """Raum mit unerkannter Unruhe (Personen, Türen): wird trotzdem fertig.

    Bekannte Grenze: Bei starken, länger anhaltenden Störungen werden die Raten eher etwas
    zu klein geschätzt (das Thermostat reagiert auf dieselbe Störung).
    """
    lr = RoomLearner()
    lr.learn_series(simulate(0.025, 0.035, noise=0.5, doors=True, seed=1))
    assert 0.15 < lr.rmse < 0.6
    assert lr.reliable, (lr.limit_reason, lr.sd_cool, lr.sd_heat)
    check(lr, 0.025, 0.035, tol_cool=0.12, tol_heat=0.2)


def test_without_flow_sensor():
    lr = RoomLearner()
    lr.learn_series(simulate(0.02, 0.03, vl_sensor=False))
    true_heat = 0.03 * 30 - 0.02 * 14
    assert lr.heat_rate(19, 5, has_vl=False) == pytest.approx(true_heat, abs=0.25)


def test_not_reliable_without_data_and_persistence():
    lr = RoomLearner()
    assert not lr.reliable and lr.progress == 0
    assert lr.limit_reason == "zu wenige Lernfenster"
    lr.learn_series(simulate(0.02, 0.03, days=1))
    lr2 = RoomLearner(lr.as_dict())
    assert lr2.theta == lr.theta and lr2.n == lr.n and lr2.q == lr.q
    assert lr2.progress == lr.progress and lr2.active == lr.active
    # alte Modellformate werden verworfen
    assert RoomLearner({"theta": [0.1, 0.1, 0.1], "n": 500}).n == 0
    assert RoomLearner({"version": 2, "theta": [0.1, 0.1, 0.1], "n": 500}).n == 0


def _fixed(theta):
    lr = RoomLearner()
    lr.fit.theta = list(theta)
    return lr


def test_minutes_to_target():
    lr = _fixed([0.02, 0.04, 0.0])
    m = lr.minutes_to_target(18.0, 20.0, 5.0, 45.0)
    assert 120 < m < 240
    assert lr.minutes_to_target(20.5, 20.0, 5.0, 45.0) == 0
    weak = _fixed([0.2, 0.005, 0.0])
    assert weak.minutes_to_target(18.0, 22.0, -10.0, 40.0) is None


def test_humidity_watch():
    w = HumidityWatch()
    assert not any(w.step(55.0) for _ in range(20))
    assert w.step(59.0)  # +4 %-Punkte -> gesperrt
    hold = sum(w.step(58.0) for _ in range(70))
    assert 50 <= hold <= 56  # 10 min Anstieg sichtbar + 45 min Nachlauf
    assert not w.step(57.0)
    assert not HumidityWatch().step(None)
    s = [Sample(20, 5, 0, None, False, False, hum=v) for v in [50] * 15 + [56] * 5]
    assert mark_disturbances(s) == 5


def test_curve():
    assert curve(0, 4) == 0 and curve(1, 4) == 1
    assert curve(0.2, 1) == pytest.approx(0.2)
    assert curve(0.2, 4) == pytest.approx(0.5904)
