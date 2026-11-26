import { useCallback, useEffect, useState } from "react";
import { fetchPrompts, type PromptVersion } from "./api";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; versions: PromptVersion[] };

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function PromptsPage() {
  const [state, setState] = useState<State>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    fetchPrompts(controller.signal)
      .then((versions) => setState({ kind: "loaded", versions }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const detail = error instanceof Error ? error.message : String(error);
        setState({ kind: "error", message: `Could not load prompt versions. ${detail}` });
      });
    return () => controller.abort();
  }, [attempt]);

  return (
    <section aria-labelledby="prompts-heading">
      <h1 id="prompts-heading">Prompts</h1>
      {state.kind === "loading" && (
        <p role="status" className="muted">
          Loading prompt versions…
        </p>
      )}
      {state.kind === "error" && (
        <div role="alert" className="error">
          <p>{state.message}</p>
          <button type="button" onClick={retry}>
            Try again
          </button>
        </div>
      )}
      {state.kind === "loaded" &&
        (state.versions.length === 0 ? (
          <p className="muted">No prompt versions exist yet.</p>
        ) : (
          <PromptsTable versions={state.versions} />
        ))}
    </section>
  );
}

function PromptsTable({ versions }: { versions: PromptVersion[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">Version</th>
            <th scope="col">Status</th>
            <th scope="col">Parent</th>
            <th scope="col">Reason</th>
            <th scope="col">Created</th>
            <th scope="col">Content</th>
          </tr>
        </thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.id} className={v.status === "active" ? "is-active" : undefined}>
              <td className="num">v{v.id}</td>
              <td>
                <span className={`badge badge-${v.status}`}>{v.status}</span>
              </td>
              <td className="num">{v.parent_id === null ? "—" : `v${v.parent_id}`}</td>
              <td>{v.change_reason}</td>
              <td>
                <time dateTime={v.created_at}>{dateFormat.format(new Date(v.created_at))}</time>
              </td>
              <td>
                <div className="content" title={v.content}>
                  {v.content}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
