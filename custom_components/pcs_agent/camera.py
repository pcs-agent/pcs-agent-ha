from __future__ import annotations

import logging

import aiohttp

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.camera.webrtc import (
    WebRTCAnswer,
    WebRTCError,
    WebRTCSendMessage,
)
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
    """Camera PC (screen o webcam) — WebRTC live nativo via go2rtc (no HLS/recording)."""

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
        if not self._ip:
            return False
        return any(c["id"] == self._cam_id for c in self.coordinator._get_cameras())

    async def stream_source(self) -> str | None:
        """RTSP fallback (HLS) — usato solo se WebRTC non disponibile."""
        ip = self._ip
        if not ip:
            return None
        return f"rtsp://{ip}:{GO2RTC_RTSP_PORT}/{self._cam_id}"

    # ── WebRTC live nativo (proxy al go2rtc del PC Agent) ───────────────
    # Implementare async_handle_async_webrtc_offer fa sì che HA 2024.11+
    # usi WebRTC (frontend_stream_type=WEB_RTC) invece di HLS. Zero recording.
    async def async_handle_async_webrtc_offer(
        self, offer_sdp: str, session_id: str, send_message: WebRTCSendMessage
    ) -> None:
        ip = self._ip
        if not ip:
            send_message(WebRTCError("pcsagent_offline", "PC Agent offline (no local IP)"))
            return
        # go2rtc WebRTC API: POST {type:offer, sdp} → {type:answer, sdp}
        url = f"http://{ip}:{GO2RTC_API_PORT}/api/webrtc?src={self._cam_id}"
        try:
            session = self.coordinator._get_session()
            async with session.post(
                url,
                json={"type": "offer", "sdp": offer_sdp},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    send_message(WebRTCError("go2rtc_http", f"go2rtc HTTP {resp.status}: {body[:120]}"))
                    return
                data = await resp.json()
            answer = data.get("sdp")
            if not answer:
                send_message(WebRTCError("go2rtc_no_answer", "go2rtc returned no SDP answer"))
                return
            send_message(WebRTCAnswer(answer))
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("WebRTC offer %s failed: %s", self._cam_id, e)
            send_message(WebRTCError("go2rtc_error", str(e)))

    async def async_on_webrtc_candidate(self, session_id: str, candidate) -> None:
        # go2rtc usa SDP non-trickle (candidati già nell'answer) → no-op
        return

    @callback
    def close_webrtc_session(self, session_id: str) -> None:
        return

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Snapshot live (frame al volo da go2rtc) per la sola anteprima card. Nessuna registrazione."""
        ip = self._ip
        if not ip:
            return None
        url = f"http://{ip}:{GO2RTC_API_PORT}/api/frame.jpeg?src={self._cam_id}"
        try:
            session = self.coordinator._get_session()
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Snapshot %s failed: %s", self._cam_id, e)
        return None
