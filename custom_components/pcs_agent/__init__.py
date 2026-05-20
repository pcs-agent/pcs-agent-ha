from homeassistant.components.webhook import async_register, async_unregister
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, CONF_SERVER_URL, CONF_USER_ID, CONF_DEVICE_ID, CONF_HA_SECRET
from .coordinator import PcsAgentCoordinator
from .lovelace_dashboard import async_setup_dashboard

PLATFORMS = ["media_player", "select", "switch", "light", "button", "binary_sensor", "sensor", "number"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = PcsAgentCoordinator(
        hass,
        entry.data[CONF_SERVER_URL],
        entry.data[CONF_USER_ID],
        entry.data[CONF_DEVICE_ID],
        ha_secret=entry.data.get(CONF_HA_SECRET, ""),
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

    # Manda URL webhook direttamente al PC — così pushherà stato senza passare dal server
    try:
        from homeassistant.components.webhook import async_generate_url
        webhook_url = async_generate_url(hass, webhook_id)
        await coordinator.send_command("set_ha_webhook", webhook_url=webhook_url)
    except Exception:
        pass

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Force CONFIG category on all select entities so they don't appear in Controls
    _hide_select_entities(hass, entry, coordinator)

    await async_setup_dashboard(hass, entry, coordinator)

    return True


def _hide_select_entities(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: PcsAgentCoordinator
) -> None:
    ent_reg = er.async_get(hass)
    uids = [f"{entry.entry_id}_power"] + [
        f"{entry.entry_id}_mode_{mid}" for mid in coordinator._get_modes()
    ]
    for uid in uids:
        eid = ent_reg.async_get_entity_id("select", DOMAIN, uid)
        if eid:
            current = ent_reg.entities.get(eid)
            if current and current.entity_category != EntityCategory.CONFIG:
                ent_reg.async_update_entity(eid, entity_category=EntityCategory.CONFIG)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: PcsAgentCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        if coordinator._session and not coordinator._session.closed:
            await coordinator._session.close()
    return unload_ok
