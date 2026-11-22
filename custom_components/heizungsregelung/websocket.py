"""Websocket-Befehl für die Dashboard-Karte."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

try:  # Home Assistant ab 2026.12 nutzt probatio statt voluptuous
    import probatio as vol
except ImportError:  # pragma: no cover - ältere Versionen
    import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import CONF_OUTDOOR, DOMAIN, MODE_LABELS


def _room_dict(room: Any) -> dict[str, Any]:
    d = asdict(room)
    for key in ("exc_start", "exc_end", "exc_end_fri", "rhythm_start"):
        d[key] = d[key].strftime("%H:%M:%S") if d.get(key) else None
    return {
        "room_id": d["room_id"],
        "thermostat_type": "manual" if d["manual"] else "smart",
        "levels": d["levels"],
        "radiators": d["radiators"],
        "valve_sensors": d["valve_sensors"],
        "name": d["name"],
        "climate": d["climate"],
        "temperature_sensor": d["temperature_sensor"],
        "window_sensor": d["window_sensor"],
        "humidity_sensor": d["humidity_sensor"],
        "in_demand": d["in_demand"],
        "max_temperature": d["max_temp"],
        "away_exception": d["exc_enabled"],
        "away_exception_start": d["exc_start"],
        "away_exception_end": d["exc_end"],
        "away_exception_end_friday": d["exc_end_fri"],
        "away_exception_temperature": d["exc_temp"],
        "rhythm": d["rhythm"],
        "rhythm_weekday": d["rhythm_weekday"],
        "rhythm_start": d["rhythm_start"],
        "rhythm_duration_hours": d["rhythm_hours"],
        "rhythm_interval_days": d["rhythm_days"],
        "rhythm_temperature": d["rhythm_temp"],
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/card_config"})
@callback
def ws_card_config(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Räume, Personen und Entitäts-IDs der Integration für die Karte."""
    entry = next(
        (e for e in hass.config_entries.async_entries(DOMAIN) if e.state is ConfigEntryState.LOADED),
        None,
    )
    if entry is None:
        connection.send_error(msg["id"], "not_loaded", "Heizungsregelung ist nicht geladen")
        return
    controller = entry.runtime_data
    prefix = f"{entry.entry_id}_"
    entities = {
        e.unique_id[len(prefix):]: e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.unique_id.startswith(prefix)
    }
    connection.send_result(
        msg["id"],
        {
            "version": entry.version,
            "boiler": controller.boiler,
            "outdoor_sensor": controller.conf.get(CONF_OUTDOOR),
            "persons": controller.persons,
            "modes": list(MODE_LABELS.values()),
            "rooms": [_room_dict(r) for r in controller.rooms],
            "entities": entities,
        },
    )


@callback
def async_register(hass: HomeAssistant) -> None:
    """Befehl einmalig registrieren."""
    websocket_api.async_register_command(hass, ws_card_config)
