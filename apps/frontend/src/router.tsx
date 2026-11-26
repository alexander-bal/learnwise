import { useEffect, useRef, useState, type MouseEvent, type ReactNode, type RefObject } from "react";

export function navigate(to: string) {
  if (to === window.location.pathname + window.location.search) return;
  window.history.pushState(null, "", to);
  // A new page opens at its top, not at the scroll offset of the one it replaces.
  window.scrollTo(0, 0);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

/** The current location, kept in step with history (a tiny router, no dependency). */
export function useLocation(): URL {
  const [href, setHref] = useState(window.location.href);
  useEffect(() => {
    const update = () => setHref(window.location.href);
    window.addEventListener("popstate", update);
    return () => window.removeEventListener("popstate", update);
  }, []);
  return new URL(href);
}

export function Link({
  to,
  current,
  children,
  className,
}: {
  to: string;
  current?: boolean;
  children: ReactNode;
  className?: string;
}) {
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(to);
  };
  return (
    <a href={to} onClick={onClick} aria-current={current ? "page" : undefined} className={className}>
      {children}
    </a>
  );
}

/** Move focus to `ref` when `key` changes after the first render, so keyboard and screen
 * reader users land on the content a link opened, not on a link that is gone. */
export function useFocusOnChange(ref: RefObject<HTMLElement | null>, key: string) {
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    ref.current?.focus();
  }, [key, ref]);
}
