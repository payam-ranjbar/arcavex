/** The single way component tests mount the application, always against the fake gateway. */

import { render, type RenderResult } from "@testing-library/react";
import type { ReactNode } from "react";

import { Providers } from "../../app/providers.tsx";
import { FakeArcavexGateway, type FakeGatewayScript } from "../../gateway/index.ts";

export interface RenderAppResult extends RenderResult {
  readonly gateway: FakeArcavexGateway;
}

export interface RenderAppOptions {
  readonly script?: FakeGatewayScript;
  readonly gateway?: FakeArcavexGateway;
}

export function renderApp(children: ReactNode, options: RenderAppOptions = {}): RenderAppResult {
  const gateway = options.gateway ?? new FakeArcavexGateway(options.script ?? {});
  const result = render(<Providers gateway={gateway}>{children}</Providers>);
  return Object.assign(result, { gateway });
}
