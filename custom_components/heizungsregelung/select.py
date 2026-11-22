"""Betriebsart: Alltag, Urlaub zuhause, Urlaub weg."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeizungConfigEntry
from .const import MODE_LABELS
from .entity import HeizungEntity

_BY_LABEL = {v: k for k, v in MODE_LABELS.items()}


async def async_setup_entry(
    hass: HomeAssistant, entry: HeizungConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    entities: list[SelectEntity] = [ModeSelect(c)]
    entities += [ManualLevelSelect(c, room) for room in c.rooms if room.manual]
    async_add_entities(entities)


class ModeSelect(HeizungEntity, SelectEntity):
    _attr_icon = "mdi:home-switch-outline"
    _attr_options = list(MODE_LABELS.values())

    def __init__(self, c) -> None:
        super().__init__(c, "betriebsart", "Betriebsart")

    @property
    def current_option(self) -> str:
        return MODE_LABELS[self.controller.mode]

    async def async_select_option(self, option: str) -> None:
        await self.controller.async_set_mode(_BY_LABEL[option])


class ManualLevelSelect(HeizungEntity, SelectEntity):
    """Aktuelle Stufe eines Handthermostats (von Hand gepflegt)."""

    _attr_icon = "mdi:thermostat-box"

    def __init__(self, c, room) -> None:
        super().__init__(c, "stufe", "Thermostat-Stufe", room)
        self._attr_options = list(room.levels)

    @property
    def current_option(self) -> str:
        return self.controller.manual_level(self.room)

    @property
    def extra_state_attributes(self) -> dict:
        return {"heizkoerper": self.room.radiators} if self.room.radiators else {}

    async def async_select_option(self, option: str) -> None:
        await self.controller.async_set_manual_level(self.room.room_id, option)
