import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { PromptsPage } from "./PromptsPage";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <header className="topbar">
      <span className="brand">Triage Console</span>
      <nav>
        <a href="/" aria-current="page">
          Prompts
        </a>
      </nav>
    </header>
    <main className="page">
      <PromptsPage />
    </main>
  </StrictMode>,
);
