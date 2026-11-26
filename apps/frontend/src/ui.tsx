import type { ReactNode } from "react";
import type { LoadState } from "./useLoad";

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "medium" });

export function Time({ value }: { value: string | null }) {
  if (!value) return <span className="muted">-</span>;
  return <time dateTime={value}>{dateFormat.format(new Date(value))}</time>;
}

export function Badge({ value }: { value: string }) {
  return <span className={`badge badge-${value}`}>{value.replace(/_/g, " ")}</span>;
}

export function Mono({ value, short = false }: { value: string | null; short?: boolean }) {
  if (!value) return <span className="muted">-</span>;
  return (
    <code className="mono" title={value}>
      {short && value.length > 12 ? `${value.slice(0, 12)}…` : value}
    </code>
  );
}

/** The loading, error and loaded states every page shares. */
export function Loaded<T>({
  state,
  what,
  onRetry,
  children,
}: {
  state: LoadState<T>;
  what: string;
  onRetry: () => void;
  children: (data: T) => ReactNode;
}) {
  if (state.kind === "loading") {
    return (
      <p role="status" className="muted">
        Loading {what}…
      </p>
    );
  }
  if (state.kind === "error") {
    return (
      <div role="alert" className="error">
        <p>{state.message}</p>
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      </div>
    );
  }
  return <>{children(state.data)}</>;
}

export function Pager({
  offset,
  limit,
  total,
  onChange,
}: {
  offset: number;
  limit: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit) return null;
  const last = Math.min(offset + limit, total);
  return (
    <nav className="pager" aria-label="Pages">
      <button type="button" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        Newer
      </button>
      <span className="muted">
        {offset + 1}-{last} of {total}
      </span>
      <button type="button" disabled={last >= total} onClick={() => onChange(offset + limit)}>
        Older
      </button>
    </nav>
  );
}
