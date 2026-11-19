import { useEffect, useState } from "react";
import { api } from "../api/client";
import { Badge, Card, ErrorBox, btnCls, btnSecondaryCls } from "./ui";

type State = "loading" | "unsupported" | "insecure" | "ios-install" | "no-sw" | "denied" | "off" | "on";

function b64ToBytes(b64: string): Uint8Array {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

const isIOS = () => /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || (navigator as unknown as { standalone?: boolean }).standalone === true;

async function registration(): Promise<ServiceWorkerRegistration | undefined> {
  return navigator.serviceWorker?.getRegistration();
}

const MESSAGES: Partial<Record<State, string>> = {
  unsupported: "This browser doesn't support web push notifications.",
  insecure: "Notifications need a secure address (https://, or http://localhost on this computer). Open Veyra through your HTTPS link to enable them here.",
  "ios-install": "On iPhone and iPad, first tap Share → Add to Home Screen, then open Veyra from the home-screen icon and enable notifications there (iOS 16.4+).",
  "no-sw": "Notifications are available in the installed app and the production build (Docker), not the development server.",
  denied: "Notifications are blocked for this site. Allow them in the browser's site settings (the lock icon in the address bar), then reload.",
};

export default function Notifications() {
  const [state, setState] = useState<State>("loading");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [server, setServer] = useState<{ subscriptions: number; scheduler_enabled: boolean; cycle_interval_min: number } | null>(null);

  async function refresh() {
    api.get<typeof server>("/push/status").then(setServer).catch(() => {});
    if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      return setState(isIOS() && !isStandalone() ? "ios-install" : "unsupported");
    }
    if (!window.isSecureContext) return setState("insecure");
    const reg = await registration();
    if (!reg) return setState("no-sw");
    if (Notification.permission === "denied") return setState("denied");
    const sub = await reg.pushManager.getSubscription();
    setState(sub ? "on" : "off");
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { refresh(); }, []);

  async function enable() {
    setBusy(true); setErr(null); setInfo(null);
    try {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") { setState(perm === "denied" ? "denied" : "off"); return; }
      const reg = await registration();
      if (!reg) { setState("no-sw"); return; }
      const { public_key } = await api.get<{ public_key: string }>("/push/key");
      const existing = await reg.pushManager.getSubscription();
      const sub = existing ?? await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(public_key) });
      await api.post("/push/subscribe", sub.toJSON());
      setState("on");
      setInfo("Notifications are on for this device.");
      api.get<typeof server>("/push/status").then(setServer).catch(() => {});
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setBusy(true); setErr(null); setInfo(null);
    try {
      const sub = await (await registration())?.pushManager.getSubscription();
      if (sub) {
        await api.post("/push/unsubscribe", { endpoint: sub.endpoint });
        await sub.unsubscribe();
      }
      setState("off");
      api.get<typeof server>("/push/status").then(setServer).catch(() => {});
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true); setErr(null); setInfo(null);
    try {
      const r = await api.post<{ sent: number; failed: number; removed: number }>("/push/test");
      setInfo(r.sent ? `Test sent to ${r.sent} device(s). It should appear within a few seconds.` : "No device received it. Turn notifications on first.");
    } catch (e) {
      setErr(String((e as Error).message ?? e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Notifications">
      <div className="space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-ink-2">This device:</span>
          {state === "on" ? <Badge tone="ok">on</Badge> : state === "loading" ? <Badge>checking…</Badge> : <Badge tone={state === "off" ? "muted" : "warn"}>{state === "off" ? "off" : "unavailable"}</Badge>}
          {server && <span className="text-xs text-muted">· {server.subscriptions} device(s) subscribed in total</span>}
        </div>
        {MESSAGES[state] && <p className="text-xs text-ink-2">{MESSAGES[state]}</p>}
        <div className="flex flex-wrap gap-2">
          {state === "off" && <button className={btnCls} onClick={enable} disabled={busy}>{busy ? "Enabling…" : "Enable notifications"}</button>}
          {state === "on" && <button className={btnSecondaryCls} onClick={test} disabled={busy}>Send test notification</button>}
          {state === "on" && <button className={btnSecondaryCls} onClick={disable} disabled={busy}>Turn off on this device</button>}
        </div>
        {info && <p role="status" className="text-xs text-ink-2">{info}</p>}
        {err && <ErrorBox error={err} />}
        {server && !server.scheduler_enabled && (
          <p className="text-xs text-muted">Scheduled cycles are off, so alerts only arrive after you press Run cycle now. Set <code className="font-mono">SCHEDULER_ENABLED=true</code> on the server to check automatically.</p>
        )}
        {server?.scheduler_enabled && <p className="text-xs text-muted">Veyra checks your competitors every {Math.round(server.cycle_interval_min / 60 * 10) / 10} h and notifies every subscribed device when an alert fires.</p>}
      </div>
    </Card>
  );
}
