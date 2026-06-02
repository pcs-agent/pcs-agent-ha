from __future__ import annotations

import socket

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
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
    known_apps: set[str] = set()

    async_add_entities([PcsAgentComputerPlayer(coordinator, entry)])

    @callback
    def _check_new_apps() -> None:
        new_entities: list[MediaPlayerEntity] = []
        for app_id, app_data in coordinator._get_apps().items():
            if app_id not in known_apps:
                known_apps.add(app_id)
                new_entities.append(
                    PcsAgentAppPlayer(coordinator, entry, app_id, app_data["name"])
                )
        if new_entities:
            async_add_entities(new_entities)

    _check_new_apps()
    coordinator.async_add_listener(_check_new_apps)


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


class PcsAgentComputerPlayer(CoordinatorEntity, MediaPlayerEntity):
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
    )
    _attr_icon = "mdi:desktop-classic"
    _attr_name = "Computer"

    def __init__(self, coordinator: PcsAgentCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._mac = entry.data.get(CONF_MAC, "")
        device_name = entry.title or entry.data.get("device_id", "PC")
        self._attr_unique_id = f"{entry.entry_id}_computer"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=device_name,
            manufacturer="PCS Agent",
            model="PC Agent",
            sw_version="1.0.0",
        )

    @property
    def available(self) -> bool:
        # SEMPRE disponibile: anche a PC spento serve per Wake-on-LAN (HA manda magic packet).
        return True

    def _agent_online(self) -> bool:
        # Stato fresco (<30s) = agent raggiungibile = PC acceso
        try:
            import time as _t
            return bool(self.coordinator.data and self.coordinator.data.get("state")) and \
                   (_t.time() - self.coordinator.state_ts) < 30
        except Exception:
            return bool(self.coordinator.data and self.coordinator.data.get("state"))

    @property
    def state(self) -> MediaPlayerState:
        return MediaPlayerState.ON if self._agent_online() else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        if not self._agent_online():
            return None
        vol = self.coordinator.data.get("state", {}).get("volume") or 50
        return float(vol) / 100.0

    async def async_set_volume_level(self, volume: float) -> None:
        await self.coordinator.send_command("set_volume", volume_level=int(volume * 100))

    async def async_volume_up(self) -> None:
        await self.coordinator.send_command("adjust_volume", volume_delta=5)

    async def async_volume_down(self) -> None:
        await self.coordinator.send_command("adjust_volume", volume_delta=-5)

    async def async_turn_on(self) -> None:
        if self._mac:
            await self.hass.async_add_executor_job(_send_wol, self._mac)
        await self.coordinator.send_command("wake")

    async def async_turn_off(self) -> None:
        await self.coordinator.send_command("shutdown")


class PcsAgentAppPlayer(CoordinatorEntity, MediaPlayerEntity):
    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
    )
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
    def state(self) -> MediaPlayerState:
        running = self.coordinator._get_apps().get(self._app_id, {}).get("running", False)
        return MediaPlayerState.ON if running else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        vol = self.coordinator._get_apps().get(self._app_id, {}).get("volume") or 50
        return float(vol) / 100.0

    async def async_set_volume_level(self, volume: float) -> None:
        # app Windows ascolta "set_volume_app" con campo "app_name"
        await self.coordinator.send_command("set_volume_app", app_name=self._app_id, volume_level=int(volume * 100))

    async def async_volume_up(self) -> None:
        await self.coordinator.send_command("adjust_volume_app", app_name=self._app_id, volume_delta=5)

    async def async_volume_down(self) -> None:
        await self.coordinator.send_command("adjust_volume_app", app_name=self._app_id, volume_delta=-5)
