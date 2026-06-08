# PC Agent — Home Assistant Integration

Control your Windows or macOS PC directly from Home Assistant with real-time state sync.

## Features

- **Power control** — 3-state selector: `on` (Wake-on-LAN + wake) / `standby` / `off` (shutdown)
- **Volume** — system volume slider
- **Monitor** — turn monitor on/off with real state tracking
- **Lock screen** — momentary switch
- **Apps** — per-app ON/OFF toggle with live state from psutil (running/not running)
- **Modes** — per-mode 3-state selector: `attiva` / `standby` / `disattiva`
- **Auto-generated Lovelace dashboard** — a "PC Agent" panel appears in the HA sidebar automatically, no manual config needed
- **Local push** — PC Agent pushes state via webhook when on the same network.

---

## Entities per device

| Entity | Domain | Description |
|--------|--------|-------------|
| Power | `select` | on / standby / off (momentary, always returns to standby) |
| Computer | `media_player` | System volume slider + connection state |
| Monitor | `switch` | Real on/off state |
| Lock Screen | `switch` | Momentary — locks and returns to off |
| *App name* | `media_player` | Live running state via psutil, toggle open/close |
| *Mode name* | `select` | attiva / standby / disattiva |
| Online | `binary_sensor` | Connectivity sensor |
| PC Volume | `sensor` | Volume % read-only |

> **Power** and **Mode** selects are hidden from the default Controls panel — they appear only in the auto-generated "PC Agent" dashboard with inline buttons.

---

## Installation via HACS

1. In HACS → **Integrations** → ⋮ → **Custom repositories**
2. Add `https://github.com/edoardobommarito/pcs-agent` — type **Integration**
3. Install **PC Agent**, restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration**, search **PC Agent**

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
| User ID | Found in PC Agent app → Account tab |
| Device ID | Found in PC Agent app → Account tab |
| MAC Address | Optional — enables Wake-on-LAN |

---

## Dashboard

After setup a **PC Agent** entry appears in the HA sidebar automatically.

Layout:
- Device name → `[ on ] [ standby ] [ off ]`
- Volume (Device name) → slider
- Monitor toggle
- Lock Screen toggle
- Per-app toggles (live psutil state)
- Per-mode → `[ attiva ] [ standby ] [ disattiva ]`

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
- Internet connection for cloud fallback (pcs-agent.com)
