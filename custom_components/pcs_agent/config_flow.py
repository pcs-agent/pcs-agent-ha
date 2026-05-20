import voluptuous as vol
import aiohttp

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_SERVER_URL, CONF_USER_ID, CONF_DEVICE_ID, CONF_MAC, CONF_HA_SECRET

_RESOLVE_URL = "https://pcs-agent.com/api/ha/token/resolve"


async def _resolve_token(token: str) -> dict:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                _RESOLVE_URL,
                json={"token": token.strip()},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                if resp.status == 404:
                    raise ValueError("token_invalid")
                raise ValueError("cannot_connect")
    except aiohttp.ClientError:
        raise ValueError("cannot_connect")


class PcsAgentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await _resolve_token(user_input["token"])
                await self.async_set_unique_id(info["device_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"PC Agent — {info.get('device_name', info['device_id'][:12])}",
                    data={
                        CONF_SERVER_URL: info.get("server_url", "https://pcs-agent.com"),
                        CONF_USER_ID: info["user_id"],
                        CONF_DEVICE_ID: info["device_id"],
                        CONF_MAC: info.get("mac_address", ""),
                        CONF_HA_SECRET: info.get("ha_secret", ""),
                    },
                )
            except ValueError as exc:
                errors["base"] = str(exc)
            except Exception:
                errors["base"] = "unknown"

        schema = vol.Schema({
            vol.Required("token"): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
