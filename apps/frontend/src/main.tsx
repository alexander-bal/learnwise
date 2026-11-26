import { StrictMode, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { LlmLogsPage } from "./LlmLogsPage";
import { ProcessPage } from "./ProcessPage";
import { PromptsPage } from "./PromptsPage";
import { RequestsPage } from "./RequestsPage";
import { Link, useFocusOnChange, useLocation } from "./router";
import { SamplesPage } from "./SamplesPage";
import { SimulatorPage } from "./SimulatorPage";
import "./styles.css";

const PAGES = [
  { path: "/", label: "Process", render: () => <ProcessPage /> },
  { path: "/samples", label: "Samples", render: () => <SamplesPage /> },
  { path: "/prompts", label: "Prompts", render: () => <PromptsPage /> },
  { path: "/requests", label: "Requests", render: (url: URL) => <RequestsPage selected={url.searchParams.get("id")} /> },
  { path: "/llm-logs", label: "LLM Logs", render: (url: URL) => <LlmLogsPage requestId={url.searchParams.get("request_id") ?? ""} /> },
  { path: "/simulator", label: "Simulator", render: () => <SimulatorPage /> },
];

function App() {
  const url = useLocation();
  const page = PAGES.find((p) => p.path === url.pathname);
  const main = useRef<HTMLElement>(null);
  useFocusOnChange(main, url.pathname);
  useEffect(() => {
    document.title = page ? `${page.label} - Triage Console` : "Triage Console";
  }, [page]);

  return (
    <>
      <header className="topbar">
        <span className="brand">Triage Console</span>
        <nav aria-label="Main">
          {PAGES.map((p) => (
            <Link key={p.path} to={p.path} current={p === page}>
              {p.label}
            </Link>
          ))}
        </nav>
      </header>
      <main className="page" ref={main} tabIndex={-1} aria-label={page?.label}>
        {page ? (
          page.render(url)
        ) : (
          <section>
            <h1>Page not found</h1>
            <p className="muted">
              Nothing lives at {url.pathname}. <Link to="/">Go to Process</Link>.
            </p>
          </section>
        )}
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
