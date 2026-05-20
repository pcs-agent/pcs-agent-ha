from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PcsAgentCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    pass


class PcsAgentVolumeNumber(CoordinatorEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:volume-high"
    _attr_native_unit_of_measurement = "%"

    def __init__(self, coordinator: PcsAgentCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_volume"
        self._attr_name = "Volume"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        return float(self.coordinator.data.get("state", {}).get("volume", 50))

    async def async_set_native_value(self, value: float) -> None:
        if self.coordinator.is_local:
            self.hass.bus.async_fire(
                "pcs_agent_command",
                {"device_id": self.coordinator.device_id, "action": "set_volume", "volume_level": int(value)},
            )
        else:
            await self.coordinator.send_command("set_volume", volume_level=int(value))


