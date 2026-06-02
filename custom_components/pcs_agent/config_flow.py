"""Config flow LOCAL-ONLY per PC Agent.
Scoperta automatica via zeroconf (_pcsagent._tcp) sulla LAN, oppure IP manuale.
Niente cloud/token."""
from __future__ import annotations

import voluptuous as vol
import aiohttp

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import DOMAIN, CONF_HOST, CONF_PORT, CONF_DEVICE_ID, AGENT_PORT


async def _probe_agent(host: str, port: int) -> dict | None:
    """GET http://{host}:{port}/ping → {device_id, ...} se l'agent risponde."""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"http://{host}:{port}/ping",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception:
        pass
    return None


class PcsAgentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self) -> None:
        self._host: str | None = None
        self._port: int = AGENT_PORT
        self._device_id: str | None = None
        self._name: str | None = None

    # ── Zeroconf auto-discovery ──────────────────────────────────────
    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> FlowResult:
        host = discovery_info.host
        port = discovery_info.port or AGENT_PORT
        props = discovery_info.properties or {}
        device_id = props.get("device_id")
        name = props.get("device_name", "PC")
        if not device_id:
            info = await _probe_agent(host, port)
            device_id = info.get("device_id") if info else None
        if not device_id:
            return self.async_abort(reason="cannot_connect")

        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})

        self._host = host
        self._port = port
        self._device_id = device_id
        self._name = name
        self.context["title_placeholders"] = {"name": f"PC Agent — {name}"}
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=f"PC Agent — {self._name}",
                data={
                    CONF_HOST: self._host,
                    CONF_PORT: self._port,
                    CONF_DEVICE_ID: self._device_id,
                },
            )
        return self.async_show_form(
            step_id="confirm",
            description_placeholders={"name": self._name, "host": self._host},
        )

    # ── Manuale (IP) ─────────────────────────────────────────────────
    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input.get(CONF_PORT, AGENT_PORT))
            info = await _probe_agent(host, port)
            if not info or not info.get("device_id"):
                errors["base"] = "cannot_connect"
            else:
                device_id = info["device_id"]
                await self.async_set_unique_id(device_id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
                return self.async_create_entry(
                    title=f"PC Agent — {device_id[:12]}",
                    data={CONF_HOST: host, CONF_PORT: port, CONF_DEVICE_ID: device_id},
                )
        schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Optional(CONF_PORT, default=AGENT_PORT): int,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
