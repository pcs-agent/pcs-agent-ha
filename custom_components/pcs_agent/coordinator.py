from datetime import timedelta
import logging
import aiohttp

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant

from .const import DOMAIN, SCAN_INTERVAL, AGENT_PORT

_LOGGER = logging.getLogger(__name__)


class PcsAgentCoordinator(DataUpdateCoordinator):
    """LOCAL-ONLY: legge lo stato direttamente dall'agent sulla LAN (http://{host}:8765/state).
    Niente cloud/VPS. HA disconnesso nell'agent → /state 503 → entity unavailable."""

    def __init__(self, hass: HomeAssistant, host: str, device_id: str, port: int = AGENT_PORT):
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.host = host
        self.port = port
        self.device_id = device_id
        self._session: aiohttp.ClientSession | None = None
        # id della pipeline Assist "Talk to {PC}" auto-creata (per la card talkback)
        self._talkback_pipeline_id: str | None = None

    @property
    def _base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def async_push_update(self, data: dict) -> None:
        self.async_set_updated_data(data)

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _async_update_data(self) -> dict:
        try:
            async with self._get_session().get(
                f"{self._base}/state",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                # 503 = HA disconnesso nell'agent. Trattato come unreachable:
                # last_update_success=False → tutte le entity unavailable.
                # ECCEZIONE: Computer media_player ha available=True (override) →
                # resta su anche qui per il Wake-on-LAN.
                raise UpdateFailed(f"HTTP {resp.status}")
        except aiohttp.ClientError as e:
            raise UpdateFailed(f"Agent unreachable: {e}")

    async def send_command(self, action: str, **kwargs) -> bool:
        try:
            async with self._get_session().post(
                f"{self._base}/",
                json={"action": action, **kwargs},
                timeout=aiohttp.ClientTimeout(total=3),
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

    @property
    def state_ts(self) -> float:
        """Timestamp (epoch) dell'ultimo state pushato dall'agent. 0 se assente."""
        try:
            return float((self.data or {}).get("state", {}).get("ts", 0) or 0)
        except (TypeError, ValueError):
            return 0.0

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
