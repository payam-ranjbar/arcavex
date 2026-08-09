/** WebView entry point: bind a gateway once and hand the tree to React. */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App.tsx";
import { Providers } from "./app/providers.tsx";
import { FakeArcavexGateway, TauriArcavexGateway, type ArcavexGateway } from "./gateway/index.ts";

/**
 * Outside Tauri there is no engine to talk to, so the deterministic fake stands in.
 *
 * This is what makes `npm run dev` and the browser end-to-end tests possible at all, and it is
 * safe in a packaged build because that build always runs inside a WebView where the Tauri
 * internals exist.
 */
function createGateway(): ArcavexGateway {
  const insideTauri = "__TAURI_INTERNALS__" in window;
  return insideTauri ? new TauriArcavexGateway() : new FakeArcavexGateway();
}

const container = document.getElementById("root");
if (container === null) {
  throw new Error("index.html must provide a #root container");
}

createRoot(container).render(
  <StrictMode>
    <Providers gateway={createGateway()}>
      <App />
    </Providers>
  </StrictMode>,
);
