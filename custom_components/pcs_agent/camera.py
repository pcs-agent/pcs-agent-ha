from __future__ import annotations

import logging
import time

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

# Stato più vecchio di questo = agent disconnesso/fermo → camera unavailable
STATE_FRESH_SECONDS = 30

# Cache thumbnail: il producer ffmpeg parte al massimo ogni TTL secondi per
# le anteprime card (il refresh thumbnail HA è ~10s, troppo aggressivo).
SNAPSHOT_TTL = 25


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
        # Cache snapshot: la card picture-entity (camera_view: auto) chiede una
        # thumbnail ~ogni 10s; ogni GET /api/frame.jpeg su go2rtc AVVIA il producer
        # ffmpeg (cattura schermo/webcam) per qualche secondo. Con la cache il
        # producer parte al massimo ogni SNAPSHOT_TTL secondi.
        self._snap_cache: bytes | None = None
        self._snap_ts: float = 0.0

    @property
    def _ip(self) -> str:
        return self.coordinator.local_ip

    @property
    def available(self) -> bool:
        # Unavailable se: ultimo poll /state fallito (HA disconnesso nell'agent → 503/down),
        # PC senza IP, camera non in lista (consent off), o stato vecchio (agent fermo).
        # Il check last_update_success rende la cam unavailable entro ~5s dal disconnect
        # (non dopo 30s), così il frontend non riapre lo stream WebRTC dopo il flush go2rtc.
        if not self.coordinator.last_update_success:
            return False
        if not self._ip:
            return False
        if not any(c["id"] == self._cam_id for c in self.coordinator._get_cameras()):
            return False
        ts = self.coordinator.state_ts
        if ts and (time.time() - ts) > STATE_FRESH_SECONDS:
            return False
        return True

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
        """Snapshot per l'anteprima card (camera_view: auto). Cache SNAPSHOT_TTL:
        ogni frame.jpeg avvia il producer ffmpeg sul PC → senza cache la cattura
        partirebbe a ogni refresh thumbnail (~10s). Nessuna registrazione."""
        now = time.time()
        if self._snap_cache is not None and (now - self._snap_ts) < SNAPSHOT_TTL:
            return self._snap_cache
        ip = self._ip
        if not ip:
            return self._snap_cache
        url = f"http://{ip}:{GO2RTC_API_PORT}/api/frame.jpeg?src={self._cam_id}"
        try:
            session = self.coordinator._get_session()
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    self._snap_cache = await resp.read()
                    self._snap_ts = now
                    return self._snap_cache
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Snapshot %s failed: %s", self._cam_id, e)
        # Fallback: meglio una thumbnail vecchia che il producer in churn
        return self._snap_cache
