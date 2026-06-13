/**
 * PCS Camera Card — live view diretto browser → go2rtc del PC Agent.
 *
 * Perché esiste: la card webrtc-camera di AlexxIT richiede l'integrazione
 * WebRTC installata su HA (si connette al SUO endpoint /api/webrtc/ws anche
 * quando si passa `server:`). Questa card usa lo stesso motore VideoRTC ma
 * si connette DIRETTAMENTE al WebSocket di go2rtc sul PC (zero proxy HA,
 * zero integrazioni extra).
 *
 * Comportamento visibilità (il punto chiave):
 *  - visibilityCheck (default VideoRTC): tab in background → DISCONNESSO,
 *    tab di nuovo visibile → riconnesso
 *  - visibilityThreshold: card fuori viewport (scroll) → DISCONNESSO
 *  → cattura schermo/webcam attiva SOLO mentre stai davvero guardando.
 */
import { VideoRTC } from './video-rtc.js?v=1.9.9';

class PcsCameraCard extends VideoRTC {
    setConfig(config) {
        if (!config.url) throw new Error('pcs-camera-card: "url" mancante');
        if (!config.server) throw new Error('pcs-camera-card: "server" mancante');
        this.config = config;

        // Stop automatico quando non visibile
        this.background = false;
        this.visibilityCheck = true;
        this.visibilityThreshold = config.intersection ?? 0.3;
        // Teardown rapido: di default VideoRTC aspetta 5s prima di chiudere la
        // connessione quando il tab si nasconde (debounce anti-flapping).
        // 1s = la cattura sul PC muore ~2s dopo che lasci la pagina.
        // (L'indicatore viola di macOS resta comunque ~20s extra: design Apple.)
        this.DISCONNECT_TIMEOUT = config.disconnect_timeout ?? 1000;

        // WebSocket diretto a go2rtc: http://ip:1984/ → ws://ip:1984/api/ws?src=name
        const base = String(config.server).replace(/^http/, 'ws').replace(/\/+$/, '');
        this.src = `${base}/api/ws?src=${encodeURIComponent(config.url)}`;
    }

    oninit() {
        super.oninit();
        // Controlli nativi: play/pausa, volume (gli stream partono muted per
        // policy autoplay dei browser — l'utente alza il volume da qui)
        this.video.controls = true;
        this.video.style.pointerEvents = 'auto';
    }

    // Lovelace inietta hass su ogni card: non ci serve, ma il setter deve esistere
    set hass(_hass) {}

    getCardSize() {
        return 5;
    }

    static getStubConfig() {
        return { url: 'screen0', server: 'http://192.168.1.x:1984/' };
    }
}

customElements.define('pcs-camera-card', PcsCameraCard);

window.customCards = window.customCards || [];
window.customCards.push({
    type: 'pcs-camera-card',
    name: 'PCS Camera',
    description: 'Live diretto dal PC Agent (go2rtc) — si ferma quando non visibile',
});
