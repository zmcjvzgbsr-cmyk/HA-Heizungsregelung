"""Sensoren: Heizbedarf, berechneter Kessel-Sollwert, Status."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeizungConfigEntry
from .entity import HeizungEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeizungConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    entities: list[SensorEntity] = [BedarfSensor(c), SollwertSensor(c), StatusSensor(c)]
    entities += [RoomDeficitSensor(c, room) for room in c.rooms if not room.manual]
    async_add_entities(entities)


class BedarfSensor(HeizungEntity, SensorEntity):
    """Größte Unterdeckung aller Räume."""

    _attr_icon = "mdi:home-thermometer"
    _attr_native_unit_of_measurement = "K"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, c) -> None:
        super().__init__(c, "heizbedarf", "Heizbedarf")

    @property
    def native_value(self) -> float | None:
        b = self.controller.snapshot.bedarf
        return b.value if b else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        b = self.controller.snapshot.bedarf
        if b is None:
            return {}
        return {"fuehrender_raum": b.leading_room, "raeume": b.deficits}


class SollwertSensor(HeizungEntity, SensorEntity):
    """Vom Regler berechneter Kessel-Sollwert."""

    _attr_icon = "mdi:water-boiler"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, c) -> None:
        super().__init__(c, "kessel_sollwert", "Kessel-Sollwert berechnet")

    @property
    def native_value(self) -> float | None:
        d = self.controller.snapshot.decision
        return d.sollwert if d else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.controller.snapshot.decision
        if d is None:
            return {}
        return {"heizen": d.heizen, "schreiben": d.schreiben, "grund": d.grund}


class StatusSensor(HeizungEntity, SensorEntity):
    """Betriebsart, Anwesenheit und die letzten Aktionen."""

    _attr_icon = "mdi:radiator"

    def __init__(self, c) -> None:
        super().__init__(c, "status", "Status")

    @property
    def native_value(self) -> str:
        return self.controller.status_text

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self.controller
        rhythm = {}
        for room in c.rooms:
            r = c.rhythm.get(room.room_id)
            if r is not None:
                rhythm[room.name] = {
                    "aktiviert": r.enabled,
                    "gerade_abwesend": r.active,
                    "von": r.von.isoformat() if r.von else None,
                    "bis": r.bis.isoformat() if r.bis else None,
                }
        return {
            "eingriffe_aktiv": c.eingriffe_aktiv,
            "betriebsart": c.mode,
            "alle_weg": c.away,
            "kessel_heizt": c.heizt,
            "rhythmus": rhythm,
            "letzte_aktionen": list(c.log)[:15],
        }


class RoomDeficitSensor(HeizungEntity, SensorEntity):
    """Unterdeckung eines Raums (Ziel minus Ist)."""

    _attr_icon = "mdi:thermometer-chevron-up"
    _attr_native_unit_of_measurement = "K"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, c, room) -> None:
        super().__init__(c, "unterdeckung", "Unterdeckung", room)

    @property
    def native_value(self) -> float | None:
        snap = self.controller.snapshot
        t = snap.room_targets.get(self.room.room_id)
        i = snap.room_currents.get(self.room.room_id)
        if t is None or i is None:
            return None
        return round(t - i, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snap = self.controller.snapshot
        return {
            "ziel": snap.room_targets.get(self.room.room_id),
            "ist": snap.room_currents.get(self.room.room_id),
            "zaehlt_fuer_bedarf": self.room.in_demand,
        }
