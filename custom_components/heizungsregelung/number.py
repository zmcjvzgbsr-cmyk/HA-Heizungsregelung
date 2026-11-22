"""Einstellbare Parameter der Regelung."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HeizungConfigEntry
from .const import PARAMS
from .entity import HeizungEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: HeizungConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    c = entry.runtime_data
    async_add_entities(ParamNumber(c, key) for key in PARAMS)


class ParamNumber(HeizungEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, c, key: str) -> None:
        name, lo, hi, step, _default, unit = PARAMS[key]
        super().__init__(c, f"param_{key}", name)
        self._key = key
        self._attr_native_min_value = lo
        self._attr_native_max_value = hi
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit

    @property
    def native_value(self) -> float:
        return self.controller.params[self._key]

    async def async_set_native_value(self, value: float) -> None:
        await self.controller.async_set_param(self._key, value)
