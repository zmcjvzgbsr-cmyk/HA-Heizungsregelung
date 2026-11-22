"""Heizungsregelung: Kessel nach Raumbedarf, Anwesenheit, Urlaub und Rhythmus-Abwesenheiten."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, PLATFORMS
from .controller import Controller
from .websocket import async_register as async_register_ws

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

CARD_FILE = "heizung-haus-card.js"
CARD_URL_BASE = f"/{DOMAIN}_frontend"

type HeizungConfigEntry = ConfigEntry[Controller]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Karte ausliefern und Websocket-Befehl registrieren (einmal je Start)."""
    async_register_ws(hass)
    await _async_register_card(hass)
    return True


async def _async_register_card(hass: HomeAssistant) -> None:
    """Die Dashboard-Karte als statische Datei bereitstellen und im Frontend laden."""
    if getattr(hass, "http", None) is None:
        return
    folder = Path(__file__).parent / "frontend"
    manifest_path = Path(__file__).parent / "manifest.json"
    manifest = await hass.async_add_executor_job(
        lambda: json.loads(manifest_path.read_text(encoding="utf-8"))
    )
    version = manifest.get("version", "0")
    try:
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL_BASE, str(folder), cache_headers=False)]
        )
    except (ImportError, AttributeError):  # pragma: no cover - sehr alte Versionen
        hass.http.register_static_path(CARD_URL_BASE, str(folder), cache_headers=False)
    except RuntimeError:
        _LOGGER.debug("Pfad %s ist bereits registriert", CARD_URL_BASE)
    try:
        from homeassistant.components.frontend import add_extra_js_url

        add_extra_js_url(hass, f"{CARD_URL_BASE}/{CARD_FILE}?v={version}")
    except (ImportError, KeyError):  # Frontend nicht geladen (z. B. in Tests)
        _LOGGER.warning("Frontend nicht verfügbar, Karte muss als Ressource eingetragen werden")


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
