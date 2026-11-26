import { useEffect, useId, useState, type FormEvent } from "react";
import { fetchCalls } from "./api";
import { CallsTable } from "./CallsTable";
import { navigate } from "./router";
import { Loaded, Pager } from "./ui";
import { useLoad } from "./useLoad";

const LIMIT = 100;
const STATUSES = ["", "running", "success", "error", "timeout"];

export function LlmLogsPage({ requestId }: { requestId: string }) {
  const ids = { request: useId(), status: useId() };
  const [draft, setDraft] = useState(requestId);
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [pagedFor, setPagedFor] = useState(`${requestId} ${status}`);
  useEffect(() => setDraft(requestId), [requestId]);
  // A new filter starts from its first page; reset during render so no stale fetch runs.
  if (pagedFor !== `${requestId} ${status}`) {
    setPagedFor(`${requestId} ${status}`);
    setOffset(0);
  }

  const { state, reload } = useLoad(
    (signal) => fetchCalls({ request_id: requestId, status }, offset, LIMIT, signal),
    [requestId, status, offset],
    "the LLM call log",
  );

  function applyFilter(event: FormEvent) {
    event.preventDefault();
    const value = draft.trim();
    navigate(value ? `/llm-logs?request_id=${encodeURIComponent(value)}` : "/llm-logs");
  }

  return (
    <section aria-labelledby="logs-heading">
      <div className="heading-row">
        <h1 id="logs-heading">LLM Logs</h1>
        <button type="button" onClick={reload}>
          Refresh
        </button>
      </div>
      <p className="muted">Every attempt of every model call, newest first. Message text and outputs are never logged.</p>
      <form className="filters" onSubmit={applyFilter}>
        <label htmlFor={ids.request}>Request id</label>
        <input id={ids.request} value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Any" />
        <label htmlFor={ids.status}>Status</label>
        <select id={ids.status} value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s || "Any"}
            </option>
          ))}
        </select>
        <button type="submit">Filter</button>
        {requestId && (
          <button type="button" onClick={() => navigate("/llm-logs")}>
            Clear
          </button>
        )}
      </form>
      <Loaded state={state} what="the LLM call log" onRetry={reload}>
        {(page) =>
          page.items.length === 0 ? (
            <p className="muted">No calls match.</p>
          ) : (
            <>
              <CallsTable calls={page.items} />
              <Pager offset={offset} limit={LIMIT} total={page.total} onChange={setOffset} />
            </>
          )
        }
      </Loaded>
    </section>
  );
}
