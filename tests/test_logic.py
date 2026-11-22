"""Tests der reinen Regel-Logik."""

from datetime import datetime, time, timedelta

from custom_components.heizungsregelung import logic

P = logic.BoilerParams(
    schub_faktor=1.5, schub_maximum=3.0, ruhe_sollwert=15.0, start_schwelle=0.3,
    stopp_schwelle=0.0, mindestpause_s=1200, sollwert_min=12, sollwert_max=26,
)


def dec(**kw):
    base = dict(bedarf=0.5, basis=20.3, aktuell=15.0, heizt=False, seit_modus_s=5000, seit_aenderung_s=5000, p=P)
    base.update(kw)
    return logic.boiler_decision(**base)


def test_bedarf_max_and_clamp():
    rooms = [
        logic.RoomInput("A", 20, 19.6),
        logic.RoomInput("B", 21, 17.0),
        logic.RoomInput("C", 18, 19.0),
    ]
    r = logic.heizbedarf(rooms, 0.5, 1800)
    assert r.value == 2.0 and r.leading_room == "B"


def test_bedarf_window_open_and_nachlauf():
    rooms = [
        logic.RoomInput("Bad", 22, 18, window_open=True),
        logic.RoomInput("Kueche", 20, 18.5, window_closed_seconds=300),
        logic.RoomInput("Flur", 15, 15.1),
    ]
    r = logic.heizbedarf(rooms, 0.5, 1800)
    assert "Bad" not in r.deficits
    assert r.value == 0.5 and r.leading_room == "Kueche"


def test_bedarf_off_and_empty():
    r = logic.heizbedarf([logic.RoomInput("A", 20, 18, heating_allowed=False)], 0.5, 1800)
    assert r.value == -2.0 and r.leading_room is None


def test_start_needs_pause_unless_big_demand():
    assert not dec(bedarf=0.5, seit_modus_s=600).heizen
    assert dec(bedarf=1.0, seit_modus_s=600).heizen
    assert dec(bedarf=0.3, seit_modus_s=1300).heizen
    assert not dec(bedarf=0.2, seit_modus_s=99999).heizen


def test_hysteresis_stop():
    assert dec(bedarf=0.1, heizt=True, aktuell=20.5).heizen
    d = dec(bedarf=0.0, heizt=True, aktuell=20.5)
    assert not d.heizen and d.sollwert == 15.0 and d.wechsel and d.schreiben


def test_setpoint_formula_and_rounding():
    d = dec(bedarf=0.6, basis=20.3)  # 20.3 + 0.9 = 21.2 -> 21.0
    assert d.sollwert == 21.0 and d.schreiben and d.grund == "Moduswechsel"
    d = dec(bedarf=2.0, basis=25.0, heizt=True, aktuell=25.0)  # 25 + 3 = 28 -> 26
    assert d.sollwert == 26.0


def test_write_rules():
    # kleine Abweichung, zu früh -> nicht schreiben
    d = dec(bedarf=1.0, basis=20.0, heizt=True, aktuell=20.5, seit_aenderung_s=300)
    assert d.sollwert == 21.5 and not d.schreiben
    # nach 15 min -> schreiben
    assert dec(bedarf=1.0, basis=20.0, heizt=True, aktuell=20.5, seit_aenderung_s=901).schreiben
    # große Abweichung sofort
    assert dec(bedarf=2.0, basis=20.0, heizt=True, aktuell=21.0, seit_aenderung_s=10).schreiben


def test_away_exception_window_friday():
    start, end, fri = time(13), time(19, 30), time(21)
    thu = datetime(2026, 11, 19, 20, 0)
    fr = datetime(2026, 11, 20, 20, 0)
    assert not logic.away_exception_active(thu, start, end, fri)
    assert logic.away_exception_active(fr, start, end, fri)
    assert not logic.away_exception_active(fr.replace(hour=12), start, end, fri)


def test_in_window_over_midnight():
    assert logic.in_window(datetime(2026, 1, 1, 23), time(22), time(5))
    assert logic.in_window(datetime(2026, 1, 1, 4, 59), time(22), time(5))
    assert not logic.in_window(datetime(2026, 1, 1, 5), time(22), time(5))


def test_rhythm_next_and_advance():
    now = datetime(2026, 11, 22, 12, 0)  # Sonntag
    von = logic.next_rhythm_start(now, 4, time(16))
    assert von == datetime(2026, 11, 27, 16, 0)
    # Freitag 16:00 genau -> nächste Woche
    assert logic.next_rhythm_start(datetime(2026, 11, 20, 16, 0), 4, time(16)) == datetime(2026, 11, 27, 16, 0)
    v, b = logic.advance_period(
        datetime(2026, 11, 20, 16), datetime(2026, 11, 22, 15), datetime(2026, 11, 22, 15, 0), 14
    )
    assert v == datetime(2026, 12, 4, 16) and b == datetime(2026, 12, 6, 15)
    v, b = logic.advance_period(v, b, v + timedelta(days=40), 14)
    assert b > v + timedelta(days=0) and v == datetime(2027, 1, 15, 16)


def test_capped():
    assert logic.capped(20, 19.5) == 19.5
    assert logic.capped(18, 19.5) == 18
    assert logic.capped(20, None) == 20
