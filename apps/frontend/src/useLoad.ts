import { useCallback, useEffect, useRef, useState } from "react";

export type LoadState<T> =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "loaded"; data: T };

/** Load data on mount and whenever `deps` change; `reload` loads it again.
 *
 * A reload keeps showing the data it replaces; a change of `deps` shows loading, so a page
 * never shows one item's data under another's heading.
 */
export function useLoad<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  what: string,
): { state: LoadState<T>; reload: () => void } {
  const [state, setState] = useState<LoadState<T>>({ kind: "loading" });
  const [attempt, setAttempt] = useState(0);
  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  const key = JSON.stringify(deps);
  const lastKey = useRef(key);

  useEffect(() => {
    const controller = new AbortController();
    const sameItem = lastKey.current === key;
    lastKey.current = key;
    setState((previous) => (sameItem && previous.kind === "loaded" ? previous : { kind: "loading" }));
    load(controller.signal)
      .then((data) => setState({ kind: "loaded", data }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        const detail = error instanceof Error ? error.message : String(error);
        setState({ kind: "error", message: `Could not load ${what}. ${detail}` });
      });
    return () => controller.abort();
    // `load` is a new closure each render; `key` and `attempt` say when to load again.
  }, [key, attempt]);

  return { state, reload };
}
