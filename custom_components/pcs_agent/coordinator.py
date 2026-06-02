from datetime import timedelta
import logging
import aiohttp

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant

from .const import DOMAIN, SCAN_INTERVAL, CONF_HA_SECRET

_LOGGER = logging.getLogger(__name__)


class PcsAgentCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, server_url: str, user_id: str, device_id: str, ha_secret: str = ""):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.server_url = server_url.rstrip("/")
        self.user_id = user_id
        self.device_id = device_id
        self.ha_secret = ha_secret
        self._session: aiohttp.ClientSession | None = None

    @property
    def _auth_headers(self) -> dict:
        if self.ha_secret:
            return {"Authorization": f"Bearer {self.ha_secret}"}
        return {}

    def async_push_update(self, data: dict) -> None:
        self.async_set_updated_data(data)

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _async_update_data(self) -> dict:
        try:
            url = f"{self.server_url}/api/ha/state/{self.device_id}"
            async with self._get_session().get(
                url,
                params={"user_id": self.user_id},
                headers=self._auth_headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                raise UpdateFailed(f"HTTP {resp.status}")
        except aiohttp.ClientError as e:
            raise UpdateFailed(f"Connection error: {e}")

    async def send_command(self, action: str, **kwargs) -> bool:
        # Prova locale prima se abbiamo l'IP del PC sulla LAN
        local_ip = (self.data or {}).get("state", {}).get("local_ip", "")
        if local_ip:
            try:
                async with self._get_session().post(
                    f"http://{local_ip}:8765/",
                    json={"action": action, **kwargs},
                    timeout=aiohttp.ClientTimeout(total=2),
                ) as resp:
                    if resp.status == 200:
                        _LOGGER.debug("HA local command: %s → %s:8765", action, local_ip)
                        return True
            except Exception:
                pass

        # Fallback VPS
        try:
            payload = {
                "user_id": self.user_id,
                "device_id": self.device_id,
                "action": action,
                **kwargs,
            }
            url = f"{self.server_url}/api/ha/command"
            async with self._get_session().post(
                url,
                json=payload,
                headers=self._auth_headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200
        except Exception:
            return False

    def _get_apps(self) -> dict[str, dict]:
        apps_raw = (self.data or {}).get("state", {}).get("apps", {})
        result = {}
        for app_id, val in apps_raw.items():
            if isinstance(val, dict):
                result[app_id] = {
                    "name": val.get("name", app_id),
                    "running": bool(val.get("running", False)),
                    "volume": val.get("volume") if val.get("volume") is not None else 50,
                }
            else:
                result[app_id] = {"name": app_id, "running": bool(val), "volume": 50}
        return result

    def _get_modes(self) -> dict[str, dict]:
        modes_raw = (self.data or {}).get("state", {}).get("modes", {})
        result = {}
        for mode_id, val in modes_raw.items():
            if isinstance(val, dict):
                result[mode_id] = {"name": val.get("name", mode_id), "active": bool(val.get("active", False))}
            else:
                result[mode_id] = {"name": mode_id, "active": bool(val)}
        return result

    @property
    def local_ip(self) -> str:
        return (self.data or {}).get("state", {}).get("local_ip", "") or ""

    def _get_cameras(self) -> list[dict]:
        """Lista camera dal PC (consent-gated lato agent).
        Ogni entry: {id: 'screen0'|'webcam0', name, type}. RTSP = rtsp://{local_ip}:8554/{id}."""
        cams = (self.data or {}).get("state", {}).get("cameras", []) or []
        result = []
        for c in cams:
            if not isinstance(c, dict):
                continue
            cid = c.get("id")
            if not cid:
                continue
            result.append({
                "id": cid,
                "name": c.get("name", cid),
                "type": c.get("type", "screen"),
            })
        return result
