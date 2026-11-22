"""Gemeinsame Basis der Entitäten."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import DOMAIN, SIGNAL_UPDATE
from .controller import Controller, RoomConfig


class HeizungEntity(Entity):
    """Basis: hängt am Controller und aktualisiert sich bei jedem Durchlauf."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: Controller, key: str, name: str, room: RoomConfig | None = None) -> None:
        self.controller = controller
        self.room = room
        entry_id = controller.entry.entry_id
        if room is None:
            self._attr_unique_id = f"{entry_id}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, entry_id)},
                name=controller.entry.title,
                manufacturer="Heizungsregelung",
                model="Regelung",
            )
        else:
            self._attr_unique_id = f"{entry_id}_{room.room_id}_{key}"
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, f"{entry_id}_{room.room_id}")},
                name=f"Heizung {room.name}",
                manufacturer="Heizungsregelung",
                model="Raum",
                via_device=(DOMAIN, entry_id),
            )
        self._attr_name = name

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATE.format(self.controller.entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
