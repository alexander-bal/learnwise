import { useEffect, useRef, useState } from "react";
import { fetchIdempotency, fetchRequest, fetchRequests, type IdempotencyRecord } from "./api";
import { CallsTable } from "./CallsTable";
import { Link, navigate } from "./router";
import { Badge, Loaded, Mono, Pager, Time } from "./ui";
import { useLoad } from "./useLoad";

const LIMIT = 50;

export function RequestsPage({ selected }: { selected: string | null }) {
  const [offset, setOffset] = useState(0);
  const { state, reload } = useLoad(
    (signal) => fetchRequests(offset, LIMIT, signal),
    [offset],
    "requests",
  );

  return (
    <section aria-labelledby="requests-heading">
      <div className="heading-row">
        <h1 id="requests-heading">Requests</h1>
        <button type="button" onClick={reload}>
          Refresh
        </button>
      </div>
      {selected && <RequestDetailPanel requestId={selected} />}
      <h2>/process requests</h2>
      <p className="muted">Requests that reached the model, one row per request id. A request refused before any model call is not listed.</p>
      <Loaded state={state} what="requests" onRetry={reload}>
        {(page) =>
          page.items.length === 0 ? (
            <p className="muted">No requests yet.</p>
          ) : (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th scope="col">Started</th>
                      <th scope="col">Request id</th>
                      <th scope="col">Outcome</th>
                      <th scope="col">Attempts</th>
                      <th scope="col">Call time</th>
                      <th scope="col">Model</th>
                      <th scope="col">Prompt</th>
                      <th scope="col">Sample</th>
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((r) => (
                      <tr key={r.request_id} className={r.request_id === selected ? "is-active" : undefined}>
                        <td>
                          <Time value={r.started_at} />
                        </td>
                        <td>
                          <Link to={`/requests?id=${encodeURIComponent(r.request_id)}`}>
                            <Mono value={r.request_id} short />
                          </Link>
                        </td>
                        <td>
                          <Badge value={r.status} /> {r.error_code && <code>{r.error_code}</code>}
                        </td>
                        <td className="num">{r.attempts}</td>
                        <td className="num">{r.total_duration_ms === null ? "-" : `${r.total_duration_ms} ms`}</td>
                        <td>
                          {r.provider} / <code>{r.model}</code>
                        </td>
                        <td className="num">{r.prompt_version_id === null ? "-" : `v${r.prompt_version_id}`}</td>
                        <td>
                          <Mono value={r.sample_id} short />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Pager offset={offset} limit={LIMIT} total={page.total} onChange={setOffset} />
            </>
          )
        }
      </Loaded>
      <IdempotencySection />
    </section>
  );
}

function RequestDetailPanel({ requestId }: { requestId: string }) {
  const { state, reload } = useLoad((signal) => fetchRequest(requestId, signal), [requestId], "the request");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    // The panel opens above the list: bring it into view and give it focus.
    heading.current?.scrollIntoView({ block: "start" });
    heading.current?.focus();
  }, [requestId]);
  return (
    <section className="card detail" aria-labelledby="detail-heading">
      <div className="heading-row">
        <h2 id="detail-heading" ref={heading} tabIndex={-1}>
          Request <Mono value={requestId} />
        </h2>
        <button type="button" onClick={() => navigate("/requests")}>
          Close
        </button>
      </div>
      <Loaded state={state} what="the request" onRetry={reload}>
        {(detail) => (
          <>
            <h3>Attempts</h3>
            {detail.calls.length === 0 ? (
              <p className="muted">No model calls.</p>
            ) : (
              <CallsTable calls={detail.calls} showRequest={false} />
            )}
            <h3>Sample</h3>
            {detail.samples.length === 0 ? (
              <p className="muted">None stored: a failed request stores no sample.</p>
            ) : (
              detail.samples.map((s) => (
                <dl className="facts" key={s.id}>
                  <dt>Id</dt>
                  <dd>
                    <Mono value={s.id} />
                  </dd>
                  <dt>Message</dt>
                  <dd className="pre">{s.input}</dd>
                  <dt>Record</dt>
                  <dd>
                    <Badge value={s.output.intent} />{" "}
                    <span className={`badge badge-urgency-${s.output.urgency}`}>{s.output.urgency}</span>
                  </dd>
                  <dt>Model settings</dt>
                  <dd>
                    <code>{s.model_settings}</code>
                  </dd>
                </dl>
              ))
            )}
            {detail.idempotency.length > 0 && (
              <>
                <h3>Idempotency key</h3>
                <IdempotencyTable records={detail.idempotency} />
              </>
            )}
            <p>
              <Link to={`/llm-logs?request_id=${encodeURIComponent(requestId)}`}>Open in LLM Logs</Link>
            </p>
          </>
        )}
      </Loaded>
    </section>
  );
}

function IdempotencySection() {
  const [offset, setOffset] = useState(0);
  const { state, reload } = useLoad(
    (signal) => fetchIdempotency(offset, LIMIT, signal),
    [offset],
    "idempotency keys",
  );
  return (
    <>
      <div className="heading-row">
        <h2>Idempotency keys</h2>
        <button type="button" onClick={reload}>
          Refresh
        </button>
      </div>
      <p className="muted">Kept for 24 hours. A completed key replays its stored response.</p>
      <Loaded state={state} what="idempotency keys" onRetry={reload}>
        {(page) =>
          page.items.length === 0 ? (
            <p className="muted">No keys yet. Send a message with an Idempotency-Key to see one.</p>
          ) : (
            <>
              <IdempotencyTable records={page.items} />
              <Pager offset={offset} limit={LIMIT} total={page.total} onChange={setOffset} />
            </>
          )
        }
      </Loaded>
    </>
  );
}

function IdempotencyTable({ records }: { records: IdempotencyRecord[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Created</th>
            <th scope="col">Key</th>
            <th scope="col">Status</th>
            <th scope="col">Lease until</th>
            <th scope="col">Stored response</th>
            <th scope="col">Sample</th>
          </tr>
        </thead>
        <tbody>
          {records.map((r) => (
            <tr key={`${r.endpoint} ${r.key}`}>
              <td>
                <Time value={r.created_at} />
              </td>
              <td>
                <Mono value={r.key} short />
              </td>
              <td>
                <Badge value={r.status} />
              </td>
              <td>
                <Time value={r.lease_expires_at} />
              </td>
              <td>
                {r.response_status === null ? (
                  <span className="muted">-</span>
                ) : (
                  <span title={JSON.stringify(r.response_body)}>HTTP {r.response_status}</span>
                )}
              </td>
              <td>
                <Mono value={r.sample_id} short />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
