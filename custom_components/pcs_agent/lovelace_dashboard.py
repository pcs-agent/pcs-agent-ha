from __future__ import annotations

import logging

from homeassistant.components.frontend import async_register_built_in_panel, async_remove_panel
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .coordinator import PcsAgentCoordinator

_LOGGER = logging.getLogger(__name__)

DASHBOARD_ID = "pcs_agent"
DASHBOARD_URL = "pcs-agent"
DASHBOARD_STORE_KEY = f"lovelace.{DASHBOARD_ID}"


async def async_setup_dashboard(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: PcsAgentCoordinator
) -> None:
    # Inject into running lovelace dashboards dict so HA serves it immediately
    try:
        from homeassistant.components.lovelace import LOVELACE_DATA  # type: ignore[attr-defined]
        from homeassistant.components.lovelace.dashboard import LovelaceStorage  # type: ignore[attr-defined]

        lovelace_data = hass.data.get(LOVELACE_DATA)
        if lovelace_data is not None and DASHBOARD_URL not in lovelace_data.dashboards:
            dash_config = {
                "id": DASHBOARD_ID,
                "url_path": DASHBOARD_URL,
                "title": "PC Agent",
                "icon": "mdi:desktop-classic",
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "storage",
            }
            lovelace_data.dashboards[DASHBOARD_URL] = LovelaceStorage(hass, dash_config)
            _LOGGER.debug("Injected PC Agent dashboard into lovelace.dashboards")

        # Persist entry in lovelace_dashboards storage so it survives restart
        dashboards_store = Store(hass, 1, "lovelace_dashboards")
        dashboards_data = await dashboards_store.async_load() or {}
        items: list[dict] = dashboards_data.get("items", [])
        if not any(i.get("url_path") == DASHBOARD_URL for i in items):
            items.append({
                "id": DASHBOARD_ID,
                "url_path": DASHBOARD_URL,
                "title": "PC Agent",
                "icon": "mdi:desktop-classic",
                "show_in_sidebar": True,
                "require_admin": False,
                "mode": "storage",
            })
            dashboards_data["items"] = items
            await dashboards_store.async_save(dashboards_data)
    except Exception:
        _LOGGER.exception("Failed to inject PC Agent into lovelace dashboards")

    # Registra panel solo se non già presente (un'altra entry potrebbe averlo già fatto)
    try:
        async_remove_panel(hass, DASHBOARD_URL)
    except Exception:
        pass
    try:
        async_register_built_in_panel(
            hass,
            component_name="lovelace",
            sidebar_title="PC Agent",
            sidebar_icon="mdi:desktop-classic",
            frontend_url_path=DASHBOARD_URL,
            config={"mode": "storage"},
            require_admin=False,
        )
    except Exception:
        pass

    def _maybe_remove_panel():
        remaining = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]
        if not remaining:
            try:
                async_remove_panel(hass, DASHBOARD_URL)
            except Exception:
                pass

    entry.async_on_unload(_maybe_remove_panel)

    await _write_config_all(hass)

    entry.async_on_unload(
        coordinator.async_add_listener(
            lambda: hass.async_create_task(_write_config_all(hass))
        )
    )


async def _write_config_all(hass: HomeAssistant) -> None:
    try:
        all_entries = hass.config_entries.async_entries(DOMAIN)
        pairs: list[tuple[ConfigEntry, PcsAgentCoordinator]] = []
        for e in all_entries:
            c = hass.data.get(DOMAIN, {}).get(e.entry_id)
            if c is not None:
                pairs.append((e, c))

        config = _build_config_multi(hass, pairs) if pairs else {
            "title": "PC Agent",
            "views": [{"title": "PC Agent", "icon": "mdi:desktop-classic", "path": "default", "cards": []}],
        }

        # Salva via LovelaceStorage (aggiorna cache in-memory + file + notifica browser)
        saved = False
        try:
            from homeassistant.components.lovelace import LOVELACE_DATA  # type: ignore[attr-defined]
            lovelace_data = hass.data.get(LOVELACE_DATA)
            if lovelace_data and DASHBOARD_URL in lovelace_data.dashboards:
                await lovelace_data.dashboards[DASHBOARD_URL].async_save(config)
                saved = True
        except Exception:
            pass

        if not saved:
            store = Store(hass, 1, DASHBOARD_STORE_KEY)
            await store.async_save({"config": config})
            hass.bus.async_fire("lovelace_updated", {"url_path": DASHBOARD_URL})
    except Exception:
        _LOGGER.exception("Failed to write PC Agent dashboard config")


def _eid(hass: HomeAssistant, domain: str, unique_id: str) -> str | None:
    reg = er.async_get(hass)
    return reg.async_get_entity_id(domain, DOMAIN, unique_id)


def _build_cards_for_device(
    hass: HomeAssistant, entry: ConfigEntry, coordinator: PcsAgentCoordinator
) -> list[dict]:
    eid = entry.entry_id
    cards: list[dict] = []

    raw_title = entry.title or entry.data.get("device_id", "PC")
    device_name = raw_title.split(" — ", 1)[-1] if " — " in raw_title else raw_title
    computer_group: list[dict] = []

    power = _eid(hass, "select", f"{eid}_power")
    if power:
        computer_group.append({
            "type": "tile",
            "entity": power,
            "name": device_name,
            "features": [{"type": "select-options"}],
        })

    computer = _eid(hass, "media_player", f"{eid}_computer")
    if computer:
        computer_group.append({
            "type": "tile",
            "entity": computer,
            "name": f"Volume ({device_name})",
            "features": [{"type": "media-player-volume-slider"}],
        })

    if len(computer_group) == 2:
        cards.append({"type": "vertical-stack", "cards": computer_group})
    else:
        cards.extend(computer_group)

    monitor = _eid(hass, "switch", f"{eid}_monitor")
    if monitor:
        cards.append({"type": "tile", "entity": monitor, "name": "Monitor"})

    lock = _eid(hass, "switch", f"{eid}_lock")
    if lock:
        cards.append({"type": "tile", "entity": lock, "name": "Blocca Schermo"})

    for app_id, app_data in coordinator._get_apps().items():
        sw_eid = _eid(hass, "switch", f"{eid}_app_{app_id}")
        vol_eid = _eid(hass, "media_player", f"{eid}_app_{app_id}")
        app_name = app_data.get("name", app_id)
        group: list[dict] = []
        if sw_eid:
            group.append({"type": "tile", "entity": sw_eid, "name": app_name})
        if vol_eid:
            group.append({
                "type": "tile",
                "entity": vol_eid,
                "name": f"Volume ({app_name})",
                "features": [{"type": "media-player-volume-slider"}],
            })
        if len(group) == 2:
            cards.append({"type": "vertical-stack", "cards": group})
        else:
            cards.extend(group)

    for mode_id, mode_data in coordinator._get_modes().items():
        mode_eid = _eid(hass, "select", f"{eid}_mode_{mode_id}")
        if mode_eid:
            cards.append({
                "type": "tile",
                "entity": mode_eid,
                "name": mode_data["name"],
                "features": [{"type": "select-options"}],
            })

    return cards


def _build_config_multi(
    hass: HomeAssistant,
    pairs: list[tuple[ConfigEntry, PcsAgentCoordinator]],
) -> dict:
    multi = len(pairs) > 1
    all_cards: list[dict] = []

    for entry, coordinator in pairs:
        device_cards = _build_cards_for_device(hass, entry, coordinator)
        if not device_cards:
            continue
        if multi:
            raw_title = entry.title or entry.data.get("device_id", "PC")
            device_name = raw_title.split(" — ", 1)[-1] if " — " in raw_title else raw_title
            all_cards.append({
                "type": "markdown",
                "content": f"## {device_name}",
            })
        all_cards.extend(device_cards)

    return {
        "title": "PC Agent",
        "views": [{
            "title": "PC Agent",
            "icon": "mdi:desktop-classic",
            "path": "default",
            "cards": all_cards,
        }],
    }
