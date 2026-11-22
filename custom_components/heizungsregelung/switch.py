"""Schalter: Eingriffe aktiv, Rhythmus-Abwesenheit je Raum."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeizungConfigEntry
from .entity import HeizungEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeizungConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    entities: list[SwitchEntity] = [EingriffeSwitch(c)]
    entities += [RhythmSwitch(c, room) for room in c.rooms if room.rhythm]
    async_add_entities(entities)


class EingriffeSwitch(HeizungEntity, SwitchEntity):
    """Aus = Beobachtungsmodus: die Regelung rechnet, schaltet aber nichts."""

    _attr_icon = "mdi:robot"

    def __init__(self, c) -> None:
        super().__init__(c, "eingriffe_aktiv", "Eingriffe aktiv")

    @property
    def is_on(self) -> bool:
        return self.controller.eingriffe_aktiv

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.controller.async_set_eingriffe(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.controller.async_set_eingriffe(False)


class RhythmSwitch(HeizungEntity, SwitchEntity):
    """Wiederkehrende Abwesenheit (z. B. jedes 2. Wochenende)."""

    _attr_icon = "mdi:calendar-sync"

    def __init__(self, c, room) -> None:
        days = room.rhythm_days
        label = "Jedes 2. Wochenende weg" if days == 14 else f"Alle {days} Tage weg"
        super().__init__(c, "rhythmus", label, room)

    @property
    def is_on(self) -> bool:
        r = self.controller.rhythm.get(self.room.room_id)
        return bool(r and r.enabled)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.controller.async_set_rhythm_enabled(self.room.room_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.controller.async_set_rhythm_enabled(self.room.room_id, False)
