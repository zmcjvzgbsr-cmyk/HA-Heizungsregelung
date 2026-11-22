"""Binärsensoren: Kessel heizt, alle weg, Raum gerade abwesend."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeizungConfigEntry
from .entity import HeizungEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeizungConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    entities: list[BinarySensorEntity] = [HeiztSensor(c), AwaySensor(c)]
    entities += [RhythmActiveSensor(c, room) for room in c.rooms if room.rhythm]
    async_add_entities(entities)


class HeiztSensor(HeizungEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, c) -> None:
        super().__init__(c, "kessel_heizt", "Kessel heizt")

    @property
    def is_on(self) -> bool:
        return self.controller.heizt


class AwaySensor(HeizungEntity, BinarySensorEntity):
    _attr_icon = "mdi:home-export-outline"

    def __init__(self, c) -> None:
        super().__init__(c, "alle_weg", "Alle weg")

    @property
    def is_on(self) -> bool:
        return self.controller.away


class RhythmActiveSensor(HeizungEntity, BinarySensorEntity):
    _attr_icon = "mdi:calendar-account"

    def __init__(self, c, room) -> None:
        super().__init__(c, "gerade_abwesend", "Gerade abwesend", room)

    @property
    def is_on(self) -> bool:
        r = self.controller.rhythm.get(self.room.room_id)
        return bool(r and r.active)
