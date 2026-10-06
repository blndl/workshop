import { useState } from "react";
import { api } from "../api";
import type { ControlResult } from "../types";

const MESSAGES: Record<ControlResult["result"], string> = {
  ok: "Done",
  no_change: "Nothing to change",
  bad_code: "Wrong code",
  locked: "Locked: too many wrong codes",
  lockout: "Too many wrong codes: locked for 5 minutes",
  arm_refused: "Arming refused",
};

export function Keypad() {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ text: string; ok: boolean } | null>(null);

  const press = (d: string) => setCode((c) => (c.length < 8 ? c + d : c));

  const send = async (action: "arm" | "disarm") => {
    if (code.length < 4) return setMessage({ text: "Code must be 4 to 8 digits", ok: false });
    setBusy(true);
    try {
      const { body } = await (action === "arm" ? api.arm(code) : api.disarm(code));
      const detail = Array.isArray(body.detail) ? `: ${body.detail.join(", ")}` : "";
      const ok = body.result === "ok" || body.result === "no_change";
      setMessage({ text: MESSAGES[body.result] + detail, ok });
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : String(e), ok: false });
    } finally {
      setCode("");
      setBusy(false);
    }
  };

  return (
    <section className="card keypad">
      <h2>Control</h2>
      <div className="keypad-display" aria-label="code">
        {code ? "•".repeat(code.length) : <span className="muted">enter code</span>}
      </div>
      <div className="keypad-grid">
        {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((d) => (
          <button key={d} onClick={() => press(d)} disabled={busy}>
            {d}
          </button>
        ))}
        <button onClick={() => setCode("")} disabled={busy} className="secondary">
          Clear
        </button>
        <button onClick={() => press("0")} disabled={busy}>
          0
        </button>
        <button onClick={() => setCode((c) => c.slice(0, -1))} disabled={busy} className="secondary">
          ⌫
        </button>
      </div>
      <div className="keypad-actions">
        <button className="arm" onClick={() => send("arm")} disabled={busy}>
          Arm
        </button>
        <button className="disarm" onClick={() => send("disarm")} disabled={busy}>
          Disarm
        </button>
      </div>
      {message && <p className={message.ok ? "msg ok" : "msg bad"}>{message.text}</p>}
    </section>
  );
}
