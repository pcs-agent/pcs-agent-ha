from __future__ import annotations

import socket

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_MAC
from .coordinator import PcsAgentCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PcsAgentCoordinator = hass.data[DOMAIN][entry.entry_id]
    known_modes: set[str] = set()

    async_add_entities([PcsAgentPowerSelect(coordinator, entry)])

    @callback
    def _check_new_modes() -> None:
        new_entities: list[SelectEntity] = []
        for mode_id, mode_data in coordinator._get_modes().items():
            if mode_id not in known_modes:
                known_modes.add(mode_id)
                new_entities.append(
                    PcsAgentModeSelect(coordinator, entry, mode_id, mode_data["name"])
                )
        if new_entities:
            async_add_entities(new_entities)

    _check_new_modes()
    coordinator.async_add_listener(_check_new_modes)


def _send_wol(mac: str) -> None:
    try:
        mac_clean = mac.replace(":", "").replace("-", "").replace(".", "")
        if len(mac_clean) != 12:
            return
        magic = b"\xff" * 6 + bytes.fromhex(mac_clean) * 16
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(magic, ("<broadcast>", 9))
    except Exception:
        pass


class PcsAgentPowerSelect(CoordinatorEntity, SelectEntity):
    _attr_options = ["on", "standby", "off"]
    _attr_icon = "mdi:power"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: PcsAgentCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._mac = entry.data.get(CONF_MAC, "")
        self._attr_unique_id = f"{entry.entry_id}_power"
        self._attr_name = "Power"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def available(self) -> bool:
        # SEMPRE disponibile: anche a PC spento/agent giù serve per mandare il
        # Wake-on-LAN (option "on"). Senza questo il select va "unavailable" e il
        # dropdown resta vuoto → impossibile accendere.
        return True

    @property
    def current_option(self) -> str:
        return "standby"

    async def async_select_option(self, option: str) -> None:
        if option == "on":
            if self._mac:
                await self.hass.async_add_executor_job(_send_wol, self._mac)
            await self.coordinator.send_command("wake")
        elif option == "off":
            await self.coordinator.send_command("shutdown")
        self.async_write_ha_state()


class PcsAgentModeSelect(CoordinatorEntity, SelectEntity):
    _attr_options = ["attiva", "standby", "disattiva"]
    _attr_icon = "mdi:cog-play"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: PcsAgentCoordinator,
        entry: ConfigEntry,
        mode_id: str,
        mode_name: str,
    ) -> None:
        super().__init__(coordinator)
        self._mode_id = mode_id
        self._attr_unique_id = f"{entry.entry_id}_mode_{mode_id}"
        self._attr_name = mode_name
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def current_option(self) -> str:
        return "standby"

    async def async_select_option(self, option: str) -> None:
        if option == "attiva":
            await self.coordinator.send_command("activate_mode", mode_id=self._mode_id)
        elif option == "disattiva":
            await self.coordinator.send_command("deactivate_mode", mode_id=self._mode_id)
        self.async_write_ha_state()
