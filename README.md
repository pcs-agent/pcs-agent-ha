# PC Agent â€” Home Assistant Integration

Control your Windows or macOS PC directly from Home Assistant with real-time state sync.

## Features

- **Power control** â€” 3-state selector: `on` (Wake-on-LAN + wake) / `standby` / `off` (shutdown)
- **Volume** â€” system volume slider
- **Monitor** â€” turn monitor on/off with real state tracking
- **Lock screen** â€” momentary switch
- **Apps** â€” per-app ON/OFF toggle with live running state
- **Modes** â€” per-mode 3-state selector: `attiva` / `standby` / `disattiva`
- **Auto-generated Lovelace dashboard** â€” a "PC Agent" panel appears in the HA sidebar automatically, no manual config needed
- **Local sync** â€” real-time state updates over your local network.

---

## Entities per device

| Entity | Domain | Description |
|--------|--------|-------------|
| Power | `select` | on / standby / off (momentary, always returns to standby) |
| Computer | `media_player` | System volume slider + connection state |
| Monitor | `switch` | Real on/off state |
| Lock Screen | `switch` | Momentary â€” locks and returns to off |
| *App name* | `media_player` | Live running state, toggle open/close |
| *Mode name* | `select` | attiva / standby / disattiva |
| Online | `binary_sensor` | Connectivity sensor |
| PC Volume | `sensor` | Volume % read-only |

> **Power** and **Mode** selects are hidden from the default Controls panel â€” they appear only in the auto-generated "PC Agent" dashboard with inline buttons.

---

## Installation via HACS

1. In HACS â†’ **Integrations** â†’ â‹® â†’ **Custom repositories**
2. Add `https://github.com/pcs-agent/pcs-agent-ha` â€” type **Integration**
3. Install **PC Agent**, restart Home Assistant
4. Go to **Settings â†’ Devices & Services â†’ Add Integration**, search **PC Agent**

## Manual installation

Copy `custom_components/pcs_agent/` into your HA config directory:
```
/config/custom_components/pcs_agent/
```
Restart Home Assistant.

---

## Configuration

| Field | Description |
|-------|-------------|
| Server URL | Leave default (`https://pcs-agent.com`) |
| User ID | Found in PC Agent app â†’ Account tab |
| Device ID | Found in PC Agent app â†’ Account tab |
| MAC Address | Optional â€” enables Wake-on-LAN |

---

## Dashboard

After setup a **PC Agent** entry appears in the HA sidebar automatically.

Layout:
- Device name â†’ `[ on ] [ standby ] [ off ]`
- Volume (Device name) â†’ slider
- Monitor toggle
- Lock Screen toggle
- Per-app toggles (live running state)
- Per-mode â†’ `[ attiva ] [ standby ] [ disattiva ]`

---

## Automations example

Shutdown PC at midnight:
```yaml
automation:
  - alias: "PC off at midnight"
    trigger:
      platform: time
      at: "00:00:00"
    action:
      service: select.select_option
      target:
        entity_id: select.pc_agent_power
      data:
        option: "off"
```

Lock screen when leaving home:
```yaml
automation:
  - alias: "Lock PC when leaving"
    trigger:
      platform: state
      entity_id: person.your_name
      to: "not_home"
    action:
      service: switch.turn_on
      target:
        entity_id: switch.lock_screen
```

---

## Requirements

- PC Agent app running on your PC/Mac
- Home Assistant 2024.1 or newer
