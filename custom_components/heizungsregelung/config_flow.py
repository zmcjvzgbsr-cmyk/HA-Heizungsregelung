"""Einrichtung und Optionen (Räume hinzufügen, bearbeiten, entfernen)."""

from __future__ import annotations

from typing import Any

try:  # Home Assistant ab 2026.12 nutzt probatio statt voluptuous
    import probatio as vol
except ImportError:  # pragma: no cover - ältere Versionen
    import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
    CONF_ABWESEND_PLAN,
    CONF_BOILER,
    CONF_LABEL_ALLTAG,
    CONF_LABEL_URLAUB,
    CONF_NOTIFY,
    CONF_PERSONS,
    CONF_ROOM_CLIMATE,
    CONF_ROOM_EXC_ENABLED,
    CONF_ROOM_EXC_END,
    CONF_ROOM_EXC_END_FRI,
    CONF_ROOM_EXC_START,
    CONF_ROOM_EXC_TEMP,
    CONF_ROOM_HEIMKEHR,
    CONF_ROOM_HUMIDITY,
    CONF_ROOM_LEVELS,
    CONF_ROOM_RADIATORS,
    CONF_ROOM_TYPE,
    ROOM_TYPE_MANUAL,
    ROOM_TYPE_SMART,
    CONF_ROOM_ID,
    CONF_ROOM_IN_DEMAND,
    CONF_ROOM_MAX_TEMP,
    CONF_ROOM_NAME,
    CONF_ROOM_REMIND,
    CONF_ROOM_REMIND_HUMIDITY,
    CONF_ROOM_REMIND_MINUTES,
    CONF_ROOM_RHYTHM,
    CONF_ROOM_RHYTHM_DAYS,
    CONF_ROOM_RHYTHM_HOURS,
    CONF_ROOM_RHYTHM_START,
    CONF_ROOM_RHYTHM_TEMP,
    CONF_ROOM_RHYTHM_WEEKDAY,
    CONF_ROOM_SENSOR,
    CONF_ROOM_WINDOW,
    CONF_ROOMS,
    DOMAIN,
    ROOM_DEFAULTS,
    WEEKDAY_LABELS,
)

SECTIONS = {
    "grund": [
        CONF_ROOM_NAME, CONF_ROOM_TYPE, CONF_ROOM_CLIMATE, CONF_ROOM_LEVELS, CONF_ROOM_RADIATORS,
        CONF_ROOM_SENSOR, CONF_ROOM_WINDOW, CONF_ROOM_IN_DEMAND, CONF_ROOM_HEIMKEHR, CONF_ROOM_MAX_TEMP,
    ],
    "ausnahme": [
        CONF_ROOM_EXC_ENABLED, CONF_ROOM_EXC_START, CONF_ROOM_EXC_END,
        CONF_ROOM_EXC_END_FRI, CONF_ROOM_EXC_TEMP,
    ],
    "rhythmus": [
        CONF_ROOM_RHYTHM, CONF_ROOM_RHYTHM_WEEKDAY, CONF_ROOM_RHYTHM_START,
        CONF_ROOM_RHYTHM_HOURS, CONF_ROOM_RHYTHM_DAYS, CONF_ROOM_RHYTHM_TEMP,
    ],
    "erinnerung": [
        CONF_ROOM_REMIND, CONF_ROOM_HUMIDITY, CONF_ROOM_REMIND_MINUTES, CONF_ROOM_REMIND_HUMIDITY,
    ],
}


def _temp(lo: float = 5, hi: float = 30, step: float = 0.5) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=lo, max=hi, step=step, unit_of_measurement="°C", mode=selector.NumberSelectorMode.BOX
        )
    )


def _num(lo: float, hi: float, step: float, unit: str) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=lo, max=hi, step=step, unit_of_measurement=unit, mode=selector.NumberSelectorMode.BOX
        )
    )


def _opt(key: str, d: dict[str, Any]) -> vol.Optional:
    """Optionales Feld mit Vorschlag (lässt sich leeren)."""
    value = d.get(key)
    if value in (None, ""):
        return vol.Optional(key)
    return vol.Optional(key, description={"suggested_value": value})


def _req(key: str, d: dict[str, Any]) -> vol.Required:
    default = d.get(key, ROOM_DEFAULTS.get(key))
    if default is None:
        return vol.Required(key)
    return vol.Required(key, default=default)


def _base_schema(hass: HomeAssistant, d: dict[str, Any]) -> vol.Schema:
    notify = sorted(f"notify.{s}" for s in hass.services.async_services_for_domain("notify"))
    return vol.Schema(
        {
            _req(CONF_BOILER, d): selector.EntitySelector(selector.EntitySelectorConfig(domain="climate")),
            _opt(CONF_PERSONS, d): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="person", multiple=True)
            ),
            _opt(CONF_LABEL_ALLTAG, d): selector.LabelSelector(),
            _opt(CONF_LABEL_URLAUB, d): selector.LabelSelector(),
            _opt(CONF_ABWESEND_PLAN, d): selector.EntitySelector(selector.EntitySelectorConfig(domain="switch")),
            _opt(CONF_NOTIFY, d): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=notify, multiple=True, custom_value=True,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _room_schema(d: dict[str, Any]) -> vol.Schema:
    weekdays = [selector.SelectOptionDict(value=str(i), label=wd) for i, wd in enumerate(WEEKDAY_LABELS)]
    grund = vol.Schema(
        {
            _req(CONF_ROOM_NAME, d): selector.TextSelector(),
            _req(CONF_ROOM_TYPE, d): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=ROOM_TYPE_SMART, label="Smartes Thermostat"),
                        selector.SelectOptionDict(value=ROOM_TYPE_MANUAL, label="Handthermostat"),
                    ],
                    mode=selector.SelectSelectorMode.LIST,
                )
            ),
            _opt(CONF_ROOM_CLIMATE, d): selector.EntitySelector(selector.EntitySelectorConfig(domain="climate")),
            _req(CONF_ROOM_LEVELS, d): selector.TextSelector(),
            _opt(CONF_ROOM_RADIATORS, d): selector.TextSelector(),
            _opt(CONF_ROOM_SENSOR, d): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
            ),
            _opt(CONF_ROOM_WINDOW, d): selector.EntitySelector(selector.EntitySelectorConfig(domain="binary_sensor")),
            _req(CONF_ROOM_IN_DEMAND, d): selector.BooleanSelector(),
            _req(CONF_ROOM_HEIMKEHR, d): selector.BooleanSelector(),
            _opt(CONF_ROOM_MAX_TEMP, d): _temp(),
        }
    )
    ausnahme = vol.Schema(
        {
            _req(CONF_ROOM_EXC_ENABLED, d): selector.BooleanSelector(),
            _opt(CONF_ROOM_EXC_START, d): selector.TimeSelector(),
            _opt(CONF_ROOM_EXC_END, d): selector.TimeSelector(),
            _opt(CONF_ROOM_EXC_END_FRI, d): selector.TimeSelector(),
            _req(CONF_ROOM_EXC_TEMP, d): _temp(),
        }
    )
    rhythmus = vol.Schema(
        {
            _req(CONF_ROOM_RHYTHM, d): selector.BooleanSelector(),
            _req(CONF_ROOM_RHYTHM_WEEKDAY, d): selector.SelectSelector(
                selector.SelectSelectorConfig(options=weekdays, mode=selector.SelectSelectorMode.DROPDOWN)
            ),
            _req(CONF_ROOM_RHYTHM_START, d): selector.TimeSelector(),
            _req(CONF_ROOM_RHYTHM_HOURS, d): _num(1, 336, 1, "h"),
            _req(CONF_ROOM_RHYTHM_DAYS, d): _num(1, 56, 1, "d"),
            _req(CONF_ROOM_RHYTHM_TEMP, d): _temp(),
        }
    )
    erinnerung = vol.Schema(
        {
            _req(CONF_ROOM_REMIND, d): selector.BooleanSelector(),
            _opt(CONF_ROOM_HUMIDITY, d): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", device_class="humidity")
            ),
            _req(CONF_ROOM_REMIND_MINUTES, d): _num(1, 240, 1, "min"),
            _req(CONF_ROOM_REMIND_HUMIDITY, d): _num(0, 100, 1, "%"),
        }
    )
    return vol.Schema(
        {
            vol.Required("grund"): section(grund, {"collapsed": False}),
            vol.Required("ausnahme"): section(ausnahme, {"collapsed": not d.get(CONF_ROOM_EXC_ENABLED)}),
            vol.Required("rhythmus"): section(rhythmus, {"collapsed": not d.get(CONF_ROOM_RHYTHM)}),
            vol.Required("erinnerung"): section(erinnerung, {"collapsed": not d.get(CONF_ROOM_REMIND)}),
        }
    )


def _flatten(user_input: dict[str, Any]) -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for name in SECTIONS:
        flat.update(user_input.get(name) or {})
    return flat


def _validate_room(flat: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if flat.get(CONF_ROOM_TYPE, ROOM_TYPE_SMART) == ROOM_TYPE_SMART and not flat.get(CONF_ROOM_CLIMATE):
        errors["base"] = "climate_required"
        return errors
    if flat.get(CONF_ROOM_TYPE) == ROOM_TYPE_MANUAL and not [
        x for x in str(flat.get(CONF_ROOM_LEVELS) or "").split(",") if x.strip()
    ]:
        errors["base"] = "levels_required"
        return errors
    if flat.get(CONF_ROOM_EXC_ENABLED) and not (flat.get(CONF_ROOM_EXC_START) and flat.get(CONF_ROOM_EXC_END)):
        errors["base"] = "exception_times"
    return errors


class HeizungConfigFlow(ConfigFlow, domain=DOMAIN):
    """Erst-Einrichtung."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Heizungsregelung", data={}, options={**user_input, CONF_ROOMS: []})
        return self.async_show_form(step_id="user", data_schema=_base_schema(self.hass, {}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HeizungOptionsFlow()


class HeizungOptionsFlow(OptionsFlow):
    """Grundeinstellungen und Räume."""

    def __init__(self) -> None:
        self._room_id: str | None = None

    @property
    def _opts(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    def _rooms(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._opts.get(CONF_ROOMS, [])]

    def _save(self, **changes: Any) -> ConfigFlowResult:
        return self.async_create_entry(data={**self._opts, **changes})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["settings", "add_room"]
        if self._rooms():
            menu += ["select_room", "remove_room"]
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            base = {k: v for k, v in self._opts.items() if k == CONF_ROOMS}
            return self.async_create_entry(data={**base, **user_input})
        return self.async_show_form(step_id="settings", data_schema=_base_schema(self.hass, self._opts))

    async def async_step_add_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            flat = _flatten(user_input)
            errors = _validate_room(flat)
            rooms = self._rooms()
            base_id = slugify(flat[CONF_ROOM_NAME]) or "raum"
            room_id, n = base_id, 2
            while any(r[CONF_ROOM_ID] == room_id for r in rooms):
                room_id, n = f"{base_id}_{n}", n + 1
            if not errors:
                rooms.append({**flat, CONF_ROOM_ID: room_id})
                return self._save(**{CONF_ROOMS: rooms})
            defaults = flat
        else:
            defaults = {}
        return self.async_show_form(step_id="add_room", data_schema=_room_schema(defaults), errors=errors)

    async def async_step_select_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._room_id = user_input[CONF_ROOM_ID]
            return await self.async_step_edit_room()
        return self.async_show_form(step_id="select_room", data_schema=self._room_picker())

    async def async_step_edit_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        rooms = self._rooms()
        idx = next(i for i, r in enumerate(rooms) if r[CONF_ROOM_ID] == self._room_id)
        errors: dict[str, str] = {}
        if user_input is not None:
            flat = _flatten(user_input)
            errors = _validate_room(flat)
            if not errors:
                rooms[idx] = {**flat, CONF_ROOM_ID: self._room_id}
                return self._save(**{CONF_ROOMS: rooms})
            defaults = flat
        else:
            defaults = rooms[idx]
        return self.async_show_form(
            step_id="edit_room",
            data_schema=_room_schema(defaults),
            errors=errors,
            description_placeholders={"name": rooms[idx][CONF_ROOM_NAME]},
        )

    async def async_step_remove_room(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            rooms = [r for r in self._rooms() if r[CONF_ROOM_ID] != user_input[CONF_ROOM_ID]]
            return self._save(**{CONF_ROOMS: rooms})
        return self.async_show_form(step_id="remove_room", data_schema=self._room_picker())

    def _room_picker(self) -> vol.Schema:
        options = [
            selector.SelectOptionDict(value=r[CONF_ROOM_ID], label=r[CONF_ROOM_NAME]) for r in self._rooms()
        ]
        return vol.Schema(
            {
                vol.Required(CONF_ROOM_ID): selector.SelectSelector(
                    selector.SelectSelectorConfig(options=options, mode=selector.SelectSelectorMode.LIST)
                )
            }
        )
