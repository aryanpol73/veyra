import { FormEvent, useState } from "react";
import { api } from "../api/client";
import { ErrorBox, btnCls, inputCls } from "../components/ui";
import { VeyraMark } from "../components/icons";

export default function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await api.post("/auth/login", { password });
      setPassword("");
      onDone();
    } catch (e) {
      const msg = String((e as Error).message);
      setErr(msg.startsWith("401") ? "Wrong password." : msg.startsWith("429") ? "Too many attempts. Try again in 15 minutes." : msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-5 rounded-[6px] border border-line bg-surface p-7" aria-labelledby="login-title">
        <div className="flex items-center gap-3">
          <VeyraMark size={40} />
          <div>
            <h1 id="login-title" className="font-display text-xl font-bold tracking-[0.12em] text-ink">VEYRA</h1>
            <p className="font-mono text-[11px] text-muted">hypothesis-driven competitive intelligence</p>
          </div>
        </div>
        <label className="block text-sm text-ink-2">
          Admin password
          <input
            type="password" autoComplete="current-password" required autoFocus value={password}
            onChange={(e) => setPassword(e.target.value)} className={`${inputCls} mt-1.5`}
          />
        </label>
        {err && <ErrorBox error={err} />}
        <button type="submit" disabled={busy || !password} className={`${btnCls} w-full justify-center`}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        <p className="text-xs text-muted">Set by <code className="font-mono">VEYRA_ADMIN_PASSWORD</code> on the server. Sessions last 7 days.</p>
      </form>
    </main>
  );
}
