import { useId, useState, type FormEvent } from "react";
import {
  addFault,
  clearFaults,
  FAULT_TYPES,
  fetchFaults,
  fetchProvider,
  removeFault,
  switchProvider,
  type Fault,
  type FaultIn,
  type FaultType,
  type ProviderState,
} from "./api";
import { Badge, Loaded } from "./ui";
import { useLoad } from "./useLoad";

const FAULT_HELP: Record<FaultType, string> = {
  "5xx": "Answers with a server error",
  "429": "Answers 429 with a Retry-After",
  reject: "Refuses the request as sent (another 4xx)",
  never_answer: "Never answers, so the attempt times out",
  delay: "Answers after a number of seconds",
  malformed_json: "Answers with output that is not JSON",
  schema_violation: "Answers with JSON that breaks the schema",
  truncated: "Answers with output cut off at the token limit",
};

function describe(fault: Fault): string {
  const parts: string[] = [];
  if (fault.type === "429" && fault.retry_after != null) parts.push(`Retry-After ${fault.retry_after} s`);
  if (fault.type === "delay" && fault.seconds != null) parts.push(`${fault.seconds} s`);
  if (fault.status != null) parts.push(`HTTP ${fault.status}`);
  return parts.join(", ");
}

export function SimulatorPage() {
  return (
    <section aria-labelledby="sim-heading">
      <h1 id="sim-heading">Simulator</h1>
      <ProviderCard />
      <FaultsCard />
    </section>
  );
}

function ProviderCard() {
  const { state, reload } = useLoad(fetchProvider, [], "the provider");
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [override, setOverride] = useState<ProviderState | null>(null);

  async function toggle(current: ProviderState) {
    setSwitching(true);
    setError(null);
    try {
      setOverride(await switchProvider(current.current === "simulator" ? "ollama" : "simulator"));
    } catch (e) {
      setError(`Could not switch the provider. ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSwitching(false);
    }
  }

  return (
    <div className="card">
      <h2>Model provider</h2>
      <Loaded state={state} what="the provider" onRetry={reload}>
        {(loaded) => {
          const provider = override ?? loaded;
          const real = provider.current === "ollama";
          return (
            <>
              <div className="switch-row">
                <span className={real ? "muted" : "strong"}>Fake (simulator)</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={real}
                  aria-label="Use the real model server (Ollama)"
                  className={`switch ${real ? "switch-on" : ""}`}
                  disabled={switching}
                  onClick={() => toggle(provider)}
                >
                  <span className="switch-thumb" />
                </button>
                <span className={real ? "strong" : "muted"}>Real (Ollama)</span>
              </div>
              {error && (
                <div role="alert" className="error">
                  <p>{error}</p>
                </div>
              )}
              <p className="muted">
                Kept in memory by the API: restarting it goes back to the simulator. Requests in flight keep the
                provider they started with.
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Profile</th>
                      <th scope="col">Base URL</th>
                      <th scope="col">Processing model</th>
                      <th scope="col">Judge model</th>
                    </tr>
                  </thead>
                  <tbody>
                    {provider.profiles.map((p) => (
                      <tr key={p.name} className={p.name === provider.current ? "is-active" : undefined}>
                        <td>
                          {p.name} {p.name === provider.current && <Badge value="active" />}
                        </td>
                        <td>
                          <code>{p.base_url}</code>
                        </td>
                        <td>
                          <code>{p.processing_model}</code>
                        </td>
                        <td>
                          <code>{p.judge_model}</code>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <dl className="facts">
                {real && (
                  <>
                    <dt>Warm-up</dt>
                    <dd>{provider.warm_up ?? "not started"}</dd>
                  </>
                )}
                <dt>Breakers</dt>
                <dd>
                  {Object.keys(provider.breakers).length === 0 ? (
                    <span className="muted">No calls yet</span>
                  ) : (
                    Object.entries(provider.breakers).map(([model, s]) => (
                      <span key={model} className="breaker">
                        <code>{model}</code> <Badge value={s} />
                      </span>
                    ))
                  )}
                </dd>
              </dl>
              <button type="button" onClick={() => { setOverride(null); reload(); }}>
                Refresh
              </button>
            </>
          );
        }}
      </Loaded>
    </div>
  );
}

function FaultsCard() {
  const ids = { type: useId(), model: useId(), retry: useId(), seconds: useId(), status: useId() };
  const { state, reload } = useLoad(fetchFaults, [], "faults");
  const [type, setType] = useState<FaultType>("5xx");
  const [model, setModel] = useState("");
  const [retryAfter, setRetryAfter] = useState("5");
  const [seconds, setSeconds] = useState("3");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>, what: string) {
    setBusy(true);
    setError(null);
    try {
      await action();
      reload();
    } catch (e) {
      setError(`Could not ${what}. ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const fault: FaultIn = { type, model: model || null };
    if (type === "429") fault.retry_after = Number(retryAfter);
    if (type === "delay") fault.seconds = Number(seconds);
    if ((type === "5xx" || type === "reject") && status) fault.status = Number(status);
    void run(() => addFault(fault), "add the fault");
  }

  return (
    <div className="card">
      <h2>Faults</h2>
      <p className="muted">
        Set on the simulator and applied to every answer until cleared. When several match a call, the one set first
        wins; a delay waits, then the others decide. They have no effect while the provider is Ollama.
      </p>
      <form className="filters" onSubmit={submit}>
        <label htmlFor={ids.type}>Fault</label>
        <select id={ids.type} value={type} onChange={(e) => setType(e.target.value as FaultType)}>
          {FAULT_TYPES.map((t) => (
            <option key={t} value={t}>
              {t} - {FAULT_HELP[t]}
            </option>
          ))}
        </select>
        <label htmlFor={ids.model}>Model</label>
        <select id={ids.model} value={model} onChange={(e) => setModel(e.target.value)}>
          <option value="">Every model</option>
          <option value="fake">fake</option>
          <option value="fake-judge">fake-judge</option>
        </select>
        {type === "429" && (
          <>
            <label htmlFor={ids.retry}>Retry-After (s)</label>
            <input id={ids.retry} type="number" min={0} step="any" value={retryAfter} onChange={(e) => setRetryAfter(e.target.value)} required />
          </>
        )}
        {type === "delay" && (
          <>
            <label htmlFor={ids.seconds}>Delay (s)</label>
            <input id={ids.seconds} type="number" min={0} step="any" value={seconds} onChange={(e) => setSeconds(e.target.value)} required />
          </>
        )}
        {(type === "5xx" || type === "reject") && (
          <>
            <label htmlFor={ids.status}>Status (optional)</label>
            <input
              id={ids.status}
              type="number"
              min={type === "5xx" ? 500 : 400}
              max={type === "5xx" ? 599 : 499}
              placeholder={type === "5xx" ? "500" : "400"}
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            />
          </>
        )}
        <button type="submit" className="primary" disabled={busy}>
          Add fault
        </button>
      </form>
      {error && (
        <div role="alert" className="error">
          <p>{error}</p>
        </div>
      )}
      <Loaded state={state} what="faults" onRetry={reload}>
        {(faults) =>
          faults.length === 0 ? (
            <p className="muted">No faults: the simulator answers normally.</p>
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Order</th>
                      <th scope="col">Fault</th>
                      <th scope="col">Model</th>
                      <th scope="col">Details</th>
                      <th scope="col">
                        <span className="visually-hidden">Actions</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {faults.map((f, i) => (
                      <tr key={f.id}>
                        <td className="num">{i + 1}</td>
                        <td>
                          <code>{f.type}</code> <span className="muted">{FAULT_HELP[f.type]}</span>
                        </td>
                        <td>{f.model ?? <span className="muted">every model</span>}</td>
                        <td>{describe(f) || <span className="muted">-</span>}</td>
                        <td>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => void run(() => removeFault(f.id), "remove the fault")}
                            aria-label={`Remove fault ${i + 1}, ${f.type}`}
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="actions">
                <button type="button" disabled={busy} onClick={() => void run(clearFaults, "clear the faults")}>
                  Clear all faults
                </button>
              </div>
            </>
          )
        }
      </Loaded>
    </div>
  );
}
