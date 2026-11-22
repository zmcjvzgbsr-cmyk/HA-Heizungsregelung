"""Einrichtung mit echtem Home Assistant (pytest-homeassistant-custom-component)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, label_registry as lr
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

DOMAIN = "heizungsregelung"


@pytest.fixture(autouse=True)
def _custom(enable_custom_integrations):
    yield


def _states(hass: HomeAssistant) -> None:
    hass.states.async_set("climate.remeha", "heat", {"temperature": 15.0, "current_temperature": 20.3})
    for e, t in [("climate.vincent", 18), ("climate.fabienne", 18)]:
        hass.states.async_set(e, "heat", {"temperature": t, "current_temperature": 18.0})
    hass.states.async_set("sensor.t_vincent", "18.2", {"device_class": "temperature"})
    hass.states.async_set("binary_sensor.f_vincent", "off")
    hass.states.async_set("person.paul", "home")
    hass.states.async_set("sensor.aussen", "5.0", {"device_class": "temperature"})
    hass.states.async_set("person.susi", "home")
    hass.states.async_set("input_number.heizung_schub_faktor", "1.5")


async def test_flow_setup_rooms_and_tick(hass: HomeAssistant, hass_ws_client) -> None:
    _states(hass)
    calls = async_mock_service(hass, "climate", "set_temperature")
    lr.async_get(hass).async_create("heizplan_alltag")

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "boiler_climate": "climate.remeha",
            "outdoor_sensor": "sensor.aussen",
            "persons": ["person.paul", "person.susi"],
            "label_alltag": "heizplan_alltag",
            "notify_services": ["notify.handy"],
        },
    )
    assert result["type"] == "create_entry", result
    await asyncio.wait_for(hass.async_block_till_done(), 30)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state.value == "loaded"

    # Raum über den Options-Flow hinzufügen
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "menu"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_room"})
    assert result["type"] == "form", result
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "grund": {
                "name": "Vincent", "climate": "climate.vincent", "temperature_sensor": "sensor.t_vincent",
                "window_sensor": "binary_sensor.f_vincent", "in_demand": True, "heimkehr_boost": True,
                "max_temperature": 19.5,
            },
            "ausnahme": {
                "away_exception": True, "away_exception_start": "13:00:00", "away_exception_end": "19:30:00",
                "away_exception_end_friday": "21:00:00", "away_exception_temperature": 19.5,
            },
            "rhythmus": {
                "rhythm": True, "rhythm_weekday": "4", "rhythm_start": "16:00:00",
                "rhythm_duration_hours": 47, "rhythm_interval_days": 14, "rhythm_temperature": 18,
            },
            "erinnerung": {
                "window_reminder": False, "reminder_minutes": 15, "reminder_humidity_below": 65,
            },
        },
    )
    assert result["type"] == "create_entry", result
    await asyncio.wait_for(hass.async_block_till_done(), 30)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.state.value == "loaded"
    assert entry.options["rooms"][0]["room_id"] == "vincent"

    ents = {e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    print("ENTITIES", sorted(ents))
    assert "switch.heizungsregelung_eingriffe_aktiv" in ents
    assert "select.heizungsregelung_betriebsart" in ents
    assert "sensor.heizungsregelung_heizbedarf" in ents
    assert any(e.startswith("datetime.heizung_vincent_abwesend") for e in ents)
    for kind in ("auskuhlrate", "aufheizrate", "zeit_bis_zieltemperatur"):
        assert f"sensor.heizung_vincent_{kind}" in ents, sorted(ents)

    # Datenabfrage der Dashboard-Karte
    client = await hass_ws_client(hass)
    await client.send_json({"id": 1, "type": "heizungsregelung/card_config"})
    msg = await client.receive_json()
    assert msg["success"], msg
    res = msg["result"]
    assert res["boiler"] == "climate.remeha"
    assert res["rooms"][0]["room_id"] == "vincent" and res["rooms"][0]["away_exception_start"] == "13:00:00"
    assert res["entities"]["vincent_gerade_abwesend"].startswith("binary_sensor.")
    assert res["entities"]["param_abwesend_temp"].startswith("number.")
    assert res["entities"]["betriebsart"] == "select.heizungsregelung_betriebsart"

    # Takt laufen lassen
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await asyncio.wait_for(hass.async_block_till_done(), 30)
    bedarf = hass.states.get("sensor.heizungsregelung_heizbedarf")
    assert bedarf is not None and float(bedarf.state) == pytest.approx(-0.2, abs=0.01), bedarf
    # Beobachtungsmodus: nichts geschrieben
    assert calls == []

    # Eingriffe an -> Vincent auf Höchstwert begrenzt? (18 < 19,5 -> nichts), Kessel geschrieben
    hass.states.async_set("sensor.t_vincent", "17.0", {"device_class": "temperature"})
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.heizungsregelung_eingriffe_aktiv"}, blocking=True)
    await asyncio.wait_for(hass.async_block_till_done(), 30)
    assert hass.states.get("switch.heizungsregelung_eingriffe_aktiv").state == "on"
    assert any(c.data.get("entity_id") == "climate.remeha" for c in calls), calls

    # Handthermostat-Raum anlegen
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_room"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "grund": {
                "name": "Schlafzimmer", "thermostat_type": "manual", "manual_levels": "0, ❄, 2, 3, 4, 5",
                "radiators": "Typ 22 100x60", "in_demand": True, "heimkehr_boost": True,
            },
            "ausnahme": {"away_exception": False, "away_exception_temperature": 20},
            "rhythmus": {
                "rhythm": False, "rhythm_weekday": "4", "rhythm_start": "16:00:00",
                "rhythm_duration_hours": 47, "rhythm_interval_days": 14, "rhythm_temperature": 18,
            },
            "erinnerung": {"window_reminder": False, "reminder_minutes": 15, "reminder_humidity_below": 65},
        },
    )
    assert result["type"] == "create_entry", result
    await asyncio.wait_for(hass.async_block_till_done(), 30)
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    ents = {e.entity_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    sel = next(e for e in ents if e.startswith("select.") and "schlafzimmer" in e)
    assert hass.states.get(sel).state == "0"
    await hass.services.async_call("select", "select_option", {"entity_id": sel, "option": "❄"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(sel).state == "❄"

    # Smartes Thermostat ohne Thermostat-Entität wird abgelehnt
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "add_room"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "grund": {"name": "Test", "thermostat_type": "smart", "manual_levels": "0", "in_demand": True, "heimkehr_boost": True},
            "ausnahme": {"away_exception": False, "away_exception_temperature": 20},
            "rhythmus": {"rhythm": False, "rhythm_weekday": "4", "rhythm_start": "16:00:00", "rhythm_duration_hours": 47, "rhythm_interval_days": 14, "rhythm_temperature": 18},
            "erinnerung": {"window_reminder": False, "reminder_minutes": 15, "reminder_humidity_below": 65},
        },
    )
    assert result["type"] == "form" and result["errors"] == {"base": "climate_required"}, result
    hass.config_entries.options.async_abort(result["flow_id"])

    # Entladen
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
