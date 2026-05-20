from __future__ import annotations

import asyncio

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PcsAgentCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PcsAgentCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_apps: set[str] = set()

    async_add_entities([
        PcsAgentMonitorSwitch(coordinator, entry),
        PcsAgentLockSwitch(coordinator, entry),
    ])

    @callback
    def _check_new_apps() -> None:
        new_entities: list[SwitchEntity] = []
        for app_id, app_data in coordinator._get_apps().items():
            if app_id not in known_apps:
                known_apps.add(app_id)
                new_entities.append(
                    PcsAgentAppSwitch(coordinator, entry, app_id, app_data["name"])
                )
        if new_entities:
            async_add_entities(new_entities)

    _check_new_apps()
    coordinator.async_add_listener(_check_new_apps)


class PcsAgentMonitorSwitch(CoordinatorEntity, SwitchEntity):
    _attr_icon = "mdi:monitor"
    _attr_name = "Monitor"

    def __init__(self, coordinator: PcsAgentCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_monitor"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("state", {}).get("monitor_on", True))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.send_command("monitor_on")

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.send_command("monitor_off")


class PcsAgentLockSwitch(CoordinatorEntity, SwitchEntity):
    _attr_icon = "mdi:lock"
    _attr_name = "Lock Screen"

    def __init__(self, coordinator: PcsAgentCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_lock"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._is_on = False

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self.async_write_ha_state()
        await self.coordinator.send_command("lock")
        await asyncio.sleep(1)
        self._is_on = False
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        pass


class PcsAgentAppSwitch(CoordinatorEntity, SwitchEntity):
    _attr_icon = "mdi:application"

    def __init__(
        self,
        coordinator: PcsAgentCoordinator,
        entry: ConfigEntry,
        app_id: str,
        app_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._app_id = app_id
        self._attr_unique_id = f"{entry.entry_id}_app_{app_id}"
        self._attr_name = app_name
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator._get_apps().get(self._app_id, {}).get("running", False))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.send_command("open_app", app_id=self._app_id)

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.send_command("close_app", app_id=self._app_id)
