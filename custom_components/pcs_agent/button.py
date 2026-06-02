from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PcsAgentCoordinator

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PcsAgentCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([PcsAgentRefreshButton(coordinator, entry)])


class PcsAgentRefreshButton(CoordinatorEntity, ButtonEntity):
    """Refresh on-demand: aggiorna subito dispositivi/app/camera senza polling continuo."""
    _attr_icon = "mdi:refresh"
    _attr_name = "Refresh devices"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: PcsAgentCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_refresh"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()


class PcsAgentButton(CoordinatorEntity, ButtonEntity):
    def __init__(
        self,
        coordinator: PcsAgentCoordinator,
        entry: ConfigEntry,
        action: str,
        name: str,
        icon: str,
        device_class: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._action = action
        self._attr_unique_id = f"{entry.entry_id}_{action}"
        self._attr_name = name
        self._attr_icon = icon
        if device_class:
            self._attr_device_class = device_class
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    async def async_press(self) -> None:
        if self.coordinator.is_local:
            self.hass.bus.async_fire(
                "pcs_agent_command",
                {"device_id": self.coordinator.device_id, "action": self._action},
            )
        else:
            await self.coordinator.send_command(self._action)
