"""Tests des lernenden Raummodells mit simulierten Räumen (inkl. realer Störungen)."""

import math
import random

import pytest

from custom_components.heizungsregelung.learn import RoomLearner, Sample


def simulate(
    a, b, c=0.0, days=7, seed=1, vl_sensor=True, quant=0.01, lag_min=20.0,
    bathing=False, doors=False, sun=0.0, tout_mean=5.0, tout_amp=3.0, bang_bang=False,
):
    """Raum mit bekannten Werten simulieren (Minutentakt)."""
    rnd = random.Random(seed)
    tin, heat_eff, samples = 19.0, 0.0, []
    alpha = 1 - math.exp(-1 / lag_min)
    spike = 0.0
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
        else:
            u = max(0.0, min(1.0, (target - tin) * 2.5))
        boiler_on = u > 0.05
        vl = 44 + 6 * u if boiler_on else max(tin + 2, 25)
        d = (vl - tin) if vl_sensor else (30 if boiler_on else 0)
        heat_eff += (u * max(0, d) - heat_eff) * alpha
        gain = c + sun * max(0.0, math.sin((h - 9) / 8 * math.pi)) if 9 <= h <= 17 else c
        rate = -a * (tin - tout) + b * heat_eff + gain + rnd.gauss(0, 0.05)
        tin += rate / 60
        win = (m % 1440) in range(7 * 60, 7 * 60 + 10)  # täglich 10 min lüften (mit Sensor)
        if win:
            tin -= 0.06
        if bathing and (m % 1440) == 19 * 60 and rnd.random() < 0.6:
            spike = 2.5  # Baden: +2,5 K Dampf/Wärme, klingt ab (kein Fenstersensor)
        if doors and rnd.random() < 0.002:
            tin -= 0.4  # Tür offen, Kaltluft (unerkannt)
        spike *= math.exp(-1 / 40)
        meas = round((tin + spike) / quant) * quant
        samples.append(Sample(meas, round(tout, 1), round(u, 2), round(vl, 1) if vl_sensor else None, boiler_on, win))
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


def test_bathroom_with_disturbances():
    """Wannenbad-Fall: Baden, unerkannte Türöffnungen, Sonne."""
    lr = RoomLearner()
    lr.learn_series(simulate(0.025, 0.04, bathing=True, doors=True, sun=0.2, seed=3))
    cool_true = 0.025 * 15
    assert lr.cool_rate(20, 5) == pytest.approx(cool_true, abs=0.2), (lr.theta, lr.rmse)
    assert lr.heat_rate(19, 5, 45) > 0.2


def test_without_flow_sensor():
    lr = RoomLearner()
    lr.learn_series(simulate(0.02, 0.03, vl_sensor=False))
    true_heat = 0.03 * 30 - 0.02 * 14
    assert lr.heat_rate(19, 5, has_vl=False) == pytest.approx(true_heat, abs=0.25)


def test_not_reliable_without_data_and_persistence():
    lr = RoomLearner()
    assert not lr.reliable and lr.progress == 0
    lr.learn_series(simulate(0.02, 0.03, days=1))
    lr2 = RoomLearner(lr.as_dict())
    assert lr2.theta == lr.theta and lr2.n == lr.n and lr2.q == lr.q
    # altes Modellformat wird verworfen
    assert RoomLearner({"theta": [0.1, 0.1, 0.1], "n": 500}).n == 0


def test_minutes_to_target():
    lr = RoomLearner({"version": 2, "theta": [0.02, 0.04, 0.0], "n": 100, "n_heat": 50})
    m = lr.minutes_to_target(18.0, 20.0, 5.0, 45.0)
    assert 120 < m < 240
    assert lr.minutes_to_target(20.5, 20.0, 5.0, 45.0) == 0
    weak = RoomLearner({"version": 2, "theta": [0.2, 0.005, 0.0]})
    assert weak.minutes_to_target(18.0, 22.0, -10.0, 40.0) is None
