"""Heizungsregelung: Kessel nach Raumbedarf, Anwesenheit, Urlaub und Rhythmus-Abwesenheiten."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS
from .controller import Controller

type HeizungConfigEntry = ConfigEntry[Controller]


async def async_setup_entry(hass: HomeAssistant, entry: HeizungConfigEntry) -> bool:
    """Config-Entry einrichten."""
    controller = Controller(hass, entry)
    await controller.async_setup()
    entry.runtime_data = controller
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HeizungConfigEntry) -> bool:
    """Config-Entry entladen."""
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        await entry.runtime_data.async_unload()
    return ok


async def _async_update_listener(hass: HomeAssistant, entry: HeizungConfigEntry) -> None:
    """Nach geänderten Optionen neu laden."""
    await hass.config_entries.async_reload(entry.entry_id)
