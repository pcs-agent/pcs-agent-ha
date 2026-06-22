from datetime import timedelta
from pathlib import Path
import asyncio
import json
import logging
import aiohttp

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.core import HomeAssistant

from .const import DOMAIN, SCAN_INTERVAL, AGENT_PORT

_LOGGER = logging.getLogger(__name__)


def _read_integration_version() -> str:
    """Versione dichiarata nel manifest → inviata all'agent (header) così l'app PC Agent
    può avvisare quando esiste un update HACS più nuovo di quello installato."""
    try:
        return json.loads(
            (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
        ).get("version", "")
    except Exception:  # noqa: BLE001
        return ""


INTEGRATION_VERSION = _read_integration_version()


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
        self._sse_task: asyncio.Task | None = None

    @property
    def _base(self) -> str:
        return f"http://{self.host}:{self.port}"

    def async_push_update(self, data: dict) -> None:
        self.async_set_updated_data(data)

    def async_start_sse(self) -> None:
        """Avvia il consumer SSE (push live). Mentre è connesso il poll rallenta a 30s
        (solo heartbeat/riconnessione); se SSE cade o l'agent è vecchio (404), torna
        al poll veloce. Idempotente."""
        if self._sse_task is None or self._sse_task.done():
            self._sse_task = self.hass.async_create_background_task(
                self._sse_loop(), "pcs_agent_sse"
            )

    async def async_stop_sse(self) -> None:
        if self._sse_task is not None:
            self._sse_task.cancel()
            self._sse_task = None
        self.update_interval = timedelta(seconds=SCAN_INTERVAL)

    async def _sse_loop(self) -> None:
        while True:
            try:
                async with self._get_session().get(
                    f"{self._base}/events",
                    headers={"X-Integration-Version": INTEGRATION_VERSION},
                    timeout=aiohttp.ClientTimeout(total=None, sock_connect=5),
                ) as resp:
                    if resp.status == 404:
                        return  # agent vecchio senza /events → resta sul poll veloce
                    if resp.status != 200:
                        raise aiohttp.ClientError(f"HTTP {resp.status}")
                    # connesso: lo stato arriva push → poll solo come heartbeat lento
                    self.update_interval = timedelta(seconds=30)
                    buf = b""
                    async for chunk in resp.content.iter_any():
                        buf += chunk
                        while b"\n\n" in buf:
                            raw, buf = buf.split(b"\n\n", 1)
                            for line in raw.split(b"\n"):
                                if line.startswith(b"data:"):
                                    try:
                                        self.async_set_updated_data(
                                            json.loads(line[5:].strip())
                                        )
                                    except Exception:  # noqa: BLE001
                                        pass
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                pass
            # disconnesso → poll veloce di sicurezza + refresh, poi ritenta
            self.update_interval = timedelta(seconds=SCAN_INTERVAL)
            try:
                await self.async_request_refresh()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(5)

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _async_update_data(self) -> dict:
        try:
            async with self._get_session().get(
                f"{self._base}/state",
                headers={"X-Integration-Version": INTEGRATION_VERSION},
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
                result[mode_id] = {"name": val.get("name", mode_id), "active": bool(val.get("active", False)),
                                   "mode_type": (val.get("mode_type") or "once")}
            else:
                result[mode_id] = {"name": mode_id, "active": bool(val), "mode_type": "once"}
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
