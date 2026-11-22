"""Tests des lernenden Raummodells mit einem simulierten Raum."""

import math
import random

import pytest

from custom_components.heizungsregelung.learn import RoomLearner, Sample


def simulate(a, b, c, days=5, seed=1, vl_sensor=True, quant=0.1, windows=True):
    """Raum mit bekannten Werten simulieren (Minutentakt)."""
    rnd = random.Random(seed)
    tin, samples = 19.0, []
    for m in range(days * 24 * 60):
        h = (m / 60) % 24
        tout = 3 + 4 * math.sin((h - 9) / 24 * 2 * math.pi)
        target = 20.0 if 5 <= h < 22 else 17.0
        # einfache Thermostat-Logik mit Totband
        u = max(0.0, min(1.0, (target - tin) * 2.5))
        boiler_on = u > 0.05
        vl = 40 + 5 * u if boiler_on else max(tin + 2, 25)
        d = (vl - tin) if vl_sensor else (30 if boiler_on else 0)
        rate = -a * (tin - tout) + b * u * max(0, d) + c + rnd.gauss(0, 0.05)
        tin += rate / 60
        win = windows and (m % (24 * 60)) in range(7 * 60, 7 * 60 + 10)  # täglich 10 min lüften
        if win:
            tin -= 0.05
        meas = round(tin / quant) * quant + rnd.gauss(0, 0.02)
        samples.append(Sample(meas, round(tout, 1), round(u, 2), round(vl, 1) if vl_sensor else None, boiler_on, win))
    return samples


@pytest.mark.parametrize("a,b,c", [(0.06, 0.035, 0.0), (0.12, 0.05, 0.2), (0.04, 0.02, -0.1)])
def test_recovers_parameters(a, b, c):
    lr = RoomLearner()
    used = lr.learn_series(simulate(a, b, c))
    assert used > 300
    assert lr.reliable
    assert lr.a == pytest.approx(a, rel=0.3, abs=0.01)
    assert lr.b == pytest.approx(b, rel=0.3, abs=0.005)
    # Aufheizrate unter typischen Bedingungen auf ±0,2 K/h genau
    true_heat = b * (45 - 18) - a * (18 - 3) + c
    assert lr.heat_rate(18, 3, 45) == pytest.approx(true_heat, abs=0.2)
    true_cool = a * (20 - 3) - c
    assert lr.cool_rate(20, 3) == pytest.approx(true_cool, abs=0.15)


def test_without_flow_sensor():
    lr = RoomLearner()
    lr.learn_series(simulate(0.08, 0.04, 0.0, vl_sensor=False))
    true_heat = 0.04 * 30 - 0.08 * 15
    assert lr.heat_rate(18, 3, has_vl=False) == pytest.approx(true_heat, abs=0.2)


def test_not_reliable_without_data_and_persistence():
    lr = RoomLearner()
    assert not lr.reliable and lr.progress == 0
    lr.learn_series(simulate(0.06, 0.03, 0.0, days=1))
    lr2 = RoomLearner(lr.as_dict())
    assert lr2.theta == lr.theta and lr2.n == lr.n


def test_minutes_to_target():
    lr = RoomLearner({"theta": [0.03, 0.05, 0.0], "n": 100, "n_heat": 50, "n_cool": 50})
    m = lr.minutes_to_target(18.0, 20.0, 3.0, 45.0)
    assert 120 < m < 180  # Start 0,9 K/h, zum Ziel hin langsamer -> gut 2 h
    assert lr.minutes_to_target(20.5, 20.0, 3.0, 45.0) == 0
    weak = RoomLearner({"theta": [0.2, 0.005, 0.0]})
    assert weak.minutes_to_target(18.0, 22.0, -10.0, 40.0) is None
