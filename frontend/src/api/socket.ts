import type { WsMessage } from "./types";

type Handler = (msg: WsMessage) => void;
type StatusHandler = (connected: boolean) => void;

/** Auto-reconnecting WebSocket client (bounded backoff, 0.5 s → 5 s). */
export class StationSocket {
  private ws: WebSocket | null = null;
  private retry = 500;
  private closed = false;
  private previewTimer: number | null = null;
  private pingTimer: number | null = null;
  private previewOn = false;

  constructor(private onMessage: Handler, private onStatus: StatusHandler) {}

  start() {
    this.closed = false;
    this.open();
  }

  stop() {
    this.closed = true;
    this.ws?.close();
  }

  setPreview(on: boolean) {
    this.previewOn = on;
    this.sendPreview();
    if (on && this.previewTimer === null) {
      this.previewTimer = window.setInterval(() => this.sendPreview(), 3000);
    } else if (!on && this.previewTimer !== null) {
      window.clearInterval(this.previewTimer);
      this.previewTimer = null;
    }
  }

  private sendPreview() {
    this.send({ type: "preview", on: this.previewOn });
  }

  private send(obj: unknown) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(obj));
  }

  private open() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 500;
      this.onStatus(true);
      if (this.previewOn) this.sendPreview();
      if (this.pingTimer === null) this.pingTimer = window.setInterval(() => this.send({ type: "ping" }), 15000);
    };
    ws.onmessage = (ev) => {
      try {
        this.onMessage(JSON.parse(ev.data) as WsMessage);
      } catch {
        /* ignore malformed */
      }
    };
    ws.onclose = () => {
      this.onStatus(false);
      if (this.closed) return;
      window.setTimeout(() => this.open(), this.retry);
      this.retry = Math.min(5000, this.retry * 2);
    };
    ws.onerror = () => ws.close();
  }
}
