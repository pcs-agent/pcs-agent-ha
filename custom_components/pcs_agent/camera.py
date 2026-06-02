from __future__ import annotations

import logging

import aiohttp

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PcsAgentCoordinator

_LOGGER = logging.getLogger(__name__)

# Porte go2rtc esposte dal PC Agent sulla LAN
GO2RTC_RTSP_PORT = 8554
GO2RTC_API_PORT = 1984


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: PcsAgentCoordinator = hass.data[DOMAIN][entry.entry_id]
    known: set[str] = set()

    @callback
    def _check_new_cameras() -> None:
        new_entities: list[Camera] = []
        for cam in coordinator._get_cameras():
            cid = cam["id"]
            if cid not in known:
                known.add(cid)
                new_entities.append(
                    PcsAgentCamera(coordinator, entry, cid, cam["name"], cam["type"])
                )
        if new_entities:
            async_add_entities(new_entities)

    _check_new_cameras()
    coordinator.async_add_listener(_check_new_cameras)


class PcsAgentCamera(CoordinatorEntity, Camera):
    """Camera PC (screen o webcam) via go2rtc RTSP. HA 2024.11+ → WebRTC nativo."""

    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self,
        coordinator: PcsAgentCoordinator,
        entry: ConfigEntry,
        cam_id: str,
        cam_name: str,
        cam_type: str,
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        Camera.__init__(self)
        self._cam_id = cam_id
        self._cam_type = cam_type
        self._attr_unique_id = f"{entry.entry_id}_camera_{cam_id}"
        self._attr_name = cam_name
        self._attr_icon = "mdi:monitor-screenshot" if cam_type == "screen" else "mdi:webcam"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})

    @property
    def _ip(self) -> str:
        return self.coordinator.local_ip

    @property
    def available(self) -> bool:
        # Disponibile solo se PC raggiungibile (local_ip noto) + camera ancora nello state (consenso attivo)
        if not self._ip:
            return False
        return any(c["id"] == self._cam_id for c in self.coordinator._get_cameras())

    async def stream_source(self) -> str | None:
        ip = self._ip
        if not ip:
            return None
        # RTSP go2rtc → HA stream/WebRTC nativo
        return f"rtsp://{ip}:{GO2RTC_RTSP_PORT}/{self._cam_id}"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        ip = self._ip
        if not ip:
            return None
        # Snapshot JPEG da go2rtc API
        url = f"http://{ip}:{GO2RTC_API_PORT}/api/frame.jpeg?src={self._cam_id}"
        try:
            session = self.coordinator._get_session()
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
        except Exception as e:
            _LOGGER.debug("Snapshot %s failed: %s", self._cam_id, e)
        return None
