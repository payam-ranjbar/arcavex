/** WebView entry point: bind the real gateway once and hand the tree to React. */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App.tsx";
import { Providers } from "./app/providers.tsx";
import { TauriArcavexGateway } from "./gateway/index.ts";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("index.html must provide a #root container");
}

createRoot(container).render(
  <StrictMode>
    <Providers gateway={new TauriArcavexGateway()}>
      <App />
    </Providers>
  </StrictMode>,
);
