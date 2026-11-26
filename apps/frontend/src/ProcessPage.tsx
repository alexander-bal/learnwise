import { useId, useState, type FormEvent } from "react";
import { processMessage, type ProcessOutcome } from "./api";
import { Link } from "./router";
import { Badge, Mono } from "./ui";

const MAX_CHARS = 4000;

function newKey(): string {
  return crypto.randomUUID();
}

export function ProcessPage() {
  const ids = { message: useId(), key: useId(), hint: useId(), keyHint: useId() };
  const [message, setMessage] = useState("");
  // Every request carries a key, generated when the page loads.
  const [idempotencyKey, setIdempotencyKey] = useState(newKey);
  const [pending, setPending] = useState(false);
  const [outcome, setOutcome] = useState<ProcessOutcome | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const tooLong = message.length > MAX_CHARS;
  const key = idempotencyKey.trim();
  const keyMissing = key.length === 0;
  const canSend = message.length > 0 && !tooLong && !keyMissing && !pending;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!canSend) return;
    setPending(true);
    setFailure(null);
    try {
      setOutcome(
        await processMessage(message, { idempotencyKey: key }),
      );
    } catch (error) {
      setOutcome(null);
      const detail = error instanceof Error ? error.message : String(error);
      setFailure(`Could not reach the API. ${detail}`);
    } finally {
      setPending(false);
    }
  }

  return (
    <section aria-labelledby="process-heading">
      <h1 id="process-heading">Process a message</h1>
      <form className="card form" onSubmit={submit}>
        <label htmlFor={ids.message}>Customer message</label>
        <textarea
          id={ids.message}
          value={message}
          rows={5}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="I was charged twice for my order, please help ASAP"
          aria-describedby={ids.hint}
          aria-invalid={tooLong}
        />
        <p id={ids.hint} className={tooLong ? "hint hint-bad" : "hint muted"}>
          {message.length} / {MAX_CHARS} characters
          {tooLong && " - too long; the API refuses more than 4,000."}
        </p>

        <div className="row">
          <div className="field">
            <label htmlFor={ids.key}>Idempotency-Key</label>
            <div className="inline">
              <input
                id={ids.key}
                value={idempotencyKey}
                onChange={(e) => setIdempotencyKey(e.target.value)}
                required
                maxLength={255}
                aria-invalid={keyMissing}
                aria-describedby={ids.keyHint}
              />
              <button type="button" onClick={() => setIdempotencyKey(newKey())}>
                Generate new key
              </button>
            </div>
            <p id={ids.keyHint} className={keyMissing ? "hint hint-bad" : "hint muted"}>
              {keyMissing
                ? "A key is required. Generate one to send a new request."
                : "Sending again with this key replays the stored result; use a new key for a new message."}
            </p>
          </div>
        </div>

        <div className="actions">
          <button type="submit" className="primary" disabled={!canSend}>
            {pending ? "Processing…" : "Process message"}
          </button>
        </div>
      </form>

      <div aria-live="polite">
        {failure && (
          <div role="alert" className="error">
            <p>{failure}</p>
          </div>
        )}
        {outcome && <OutcomeView outcome={outcome} />}
      </div>
    </section>
  );
}

function OutcomeView({ outcome }: { outcome: ProcessOutcome }) {
  const requestLink = outcome.requestId && (
    <Link to={`/requests?id=${encodeURIComponent(outcome.requestId)}`}>
      <Mono value={outcome.requestId} />
    </Link>
  );

  if (outcome.ok) {
    const { record, sample_id, prompt_version, request_id } = outcome.ok;
    return (
      <div className="card result" role="status">
        <h2>
          Triage record {outcome.replayed && <span className="badge badge-replayed">replayed</span>}
        </h2>
        <dl className="facts">
          <dt>Intent</dt>
          <dd>
            <Badge value={record.intent} />
          </dd>
          <dt>Urgency</dt>
          <dd>
            <span className={`badge badge-urgency-${record.urgency}`}>{record.urgency}</span>
          </dd>
          <dt>Prompt version</dt>
          <dd>v{prompt_version}</dd>
          <dt>Sample</dt>
          <dd>
            <Mono value={sample_id} />
          </dd>
          <dt>Request id</dt>
          <dd>
            {requestLink}
            {outcome.replayed && request_id !== outcome.requestId && (
              <span className="muted"> (stored from {request_id})</span>
            )}
          </dd>
        </dl>
      </div>
    );
  }

  const error = outcome.error!;
  return (
    <div className="card result result-error" role="alert">
      <h2>
        HTTP {outcome.status}: <code>{error.code}</code>
        {outcome.replayed && <span className="badge badge-replayed">replayed</span>}
      </h2>
      <p>{error.message}</p>
      <dl className="facts">
        <dt>Retryable</dt>
        <dd>{error.retryable ? "Yes - a retry can help" : "No - change the request first"}</dd>
        {outcome.retryAfter && (
          <>
            <dt>Retry-After</dt>
            <dd>{outcome.retryAfter} s</dd>
          </>
        )}
        <dt>Request id</dt>
        <dd>{requestLink}</dd>
      </dl>
    </div>
  );
}
