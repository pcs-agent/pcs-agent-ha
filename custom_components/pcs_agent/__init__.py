import aiohttp

from homeassistant.components.webhook import async_register, async_unregister
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN, CONF_DEVICE_ID, CONF_HOST, CONF_PORT, AGENT_PORT,
    CONF_SERVER_URL, CONF_USER_ID, CONF_MAC,
)
from .coordinator import PcsAgentCoordinator
from .lovelace_dashboard import async_setup_dashboard

PLATFORMS = ["media_player", "select", "switch", "light", "button", "binary_sensor", "sensor", "number", "camera"]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrazione automatica v1 (cloud) → v2 (local-only).
    Recupera l'IP LAN dell'agent dall'ultimo stato cloud UNA volta, poi full local."""
    if entry.version >= 2 or CONF_HOST in entry.data:
        return True
    data = dict(entry.data)
    device_id = data.get(CONF_DEVICE_ID, "")
    server = data.get(CONF_SERVER_URL, "https://pcs-agent.com").rstrip("/")
    user_id = data.get(CONF_USER_ID, "")
    host = ""
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"{server}/api/ha/state/{device_id}",
                params={"user_id": user_id},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as r:
                if r.status == 200:
                    j = await r.json()
                    host = (j.get("state", {}) or {}).get("local_ip", "") or ""
    except Exception:
        host = ""
    if not host:
        # Agent offline ora → non possiamo trovare l'IP. Riprova al prossimo avvio.
        return False
    new_data = {CONF_HOST: host, CONF_PORT: AGENT_PORT, CONF_DEVICE_ID: device_id}
    # Preserva il MAC per Wake-on-LAN (HA-side magic packet, funziona a PC spento)
    if data.get(CONF_MAC):
        new_data[CONF_MAC] = data[CONF_MAC]
    hass.config_entries.async_update_entry(entry, data=new_data, version=2)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if CONF_HOST not in entry.data:
        # Migrazione non ancora riuscita (agent era offline) → ritenta
        raise ConfigEntryNotReady("Waiting for PC Agent to be reachable for migration")
    # Backfill MAC (per WOL) se manca — entry migrate prima del fix mac
    if not entry.data.get(CONF_MAC):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    f"http://{entry.data[CONF_HOST]}:{entry.data.get(CONF_PORT, AGENT_PORT)}/ping",
                    timeout=aiohttp.ClientTimeout(total=4),
                ) as r:
                    if r.status == 200:
                        mac = (await r.json()).get("mac", "")
                        if mac:
                            hass.config_entries.async_update_entry(
                                entry, data={**entry.data, CONF_MAC: mac})
        except Exception:
            pass
    coordinator = PcsAgentCoordinator(
        hass,
        entry.data[CONF_HOST],
        entry.data[CONF_DEVICE_ID],
        port=entry.data.get(CONF_PORT, AGENT_PORT),
    )
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    ent_reg = er.async_get(hass)
    stale = [
        eid
        for eid, ent in ent_reg.entities.items()
        if ent.config_entry_id == entry.entry_id
        and ent.domain == "media_player"
        and ent.unique_id != f"{entry.entry_id}_computer"
        and not ent.unique_id.startswith(f"{entry.entry_id}_app_")
    ]
    for eid in stale:
        ent_reg.async_remove(eid)

    stale_other = [
        eid
        for eid, ent in ent_reg.entities.items()
        if ent.config_entry_id == entry.entry_id
        and (
            # old power switches / select (replaced by Computer media_player)
            (ent.domain == "switch" and ent.unique_id in (
                f"{entry.entry_id}_power_switch",
                f"{entry.entry_id}_power_on",
                f"{entry.entry_id}_power_off",
            ))

            # old shutdown/wake buttons (replaced by Computer media_player)
            or (ent.domain == "button" and ent.unique_id in (
                f"{entry.entry_id}_shutdown",
                f"{entry.entry_id}_wake",
            ))
            # old volume number (volume now via Computer media_player)
            or (ent.domain == "number" and ent.unique_id == f"{entry.entry_id}_volume")
            # all mode switches (replaced by select)
            or (
                ent.domain == "switch"
                and ent.unique_id.startswith(f"{entry.entry_id}_mode_")
            )
            # old app light (replaced by switch + media_player)
            or (
                ent.domain == "light"
                and ent.unique_id.startswith(f"{entry.entry_id}_app_")
            )
            # old per-app volume numbers
            or (
                ent.domain == "number"
                and ent.unique_id.startswith(f"{entry.entry_id}_app_")
            )
        )
    ]
    for eid in stale_other:
        ent_reg.async_remove(eid)

    webhook_id = f"pcs_agent_{entry.data[CONF_DEVICE_ID]}"

    async def handle_webhook(hass: HomeAssistant, webhook_id: str, request) -> None:
        try:
            data = await request.json()
            coordinator.async_push_update(data)
        except Exception:
            pass

    async_register(hass, DOMAIN, "PC Agent State Push", webhook_id, handle_webhook)
    entry.async_on_unload(lambda: async_unregister(hass, webhook_id))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Force CONFIG category on all select entities so they don't appear in Controls
    _hide_select_entities(hass, entry, coordinator)

    await async_setup_dashboard(hass, entry, coordinator)

    return True


def _hide_select_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: PcsAgentCoordinator
) -> None:
    ent_reg = er.async_get(hass)
    # Solo il Power select resta nascosto (power è sul Computer media_player).
    power_eid = ent_reg.async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_power")
    if power_eid:
        cur = ent_reg.entities.get(power_eid)
        if cur and cur.entity_category != EntityCategory.CONFIG:
            ent_reg.async_update_entity(power_eid, entity_category=EntityCategory.CONFIG)
    # Mode selects: VISIBILI come controlli normali (rimuovi CONFIG se messo in passato).
    for mid in coordinator._get_modes():
        eid = ent_reg.async_get_entity_id("select", DOMAIN, f"{entry.entry_id}_mode_{mid}")
        if eid:
            cur = ent_reg.entities.get(eid)
            if cur and cur.entity_category is not None:
                ent_reg.async_update_entity(eid, entity_category=None)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: PcsAgentCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        if coordinator._session and not coordinator._session.closed:
            await coordinator._session.close()
    return unload_ok
