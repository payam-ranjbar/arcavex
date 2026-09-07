/** Application composition: the gateway instance and the async query cache live here. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createContext, useContext, useMemo, type ReactNode } from "react";

import type { ArcavexGateway } from "../gateway/index.ts";
import { ThemeProvider } from "../theme/ThemeProvider.tsx";

const GatewayContext = createContext<ArcavexGateway | null>(null);

/** Engine state is cached and invalidated here; it never becomes a second document model. */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, staleTime: 5_000 },
      mutations: { retry: false },
    },
  });
}

export interface ProvidersProps {
  readonly gateway: ArcavexGateway;
  readonly queryClient?: QueryClient;
  /** Which bundled or imported theme to start in; settings supply the remembered one. */
  readonly themeId?: string;
  readonly children: ReactNode;
}

export function Providers({ gateway, queryClient, themeId, children }: ProvidersProps): ReactNode {
  const client = useMemo(() => queryClient ?? createQueryClient(), [queryClient]);
  return (
    <GatewayContext.Provider value={gateway}>
      <QueryClientProvider client={client}>
        <ThemeProvider {...(themeId === undefined ? {} : { initialThemeId: themeId })}>
          {children}
        </ThemeProvider>
      </QueryClientProvider>
    </GatewayContext.Provider>
  );
}

/** Read the gateway port. Throws rather than silently rendering a disconnected workbench. */
export function useGateway(): ArcavexGateway {
  const gateway = useContext(GatewayContext);
  if (gateway === null) {
    throw new Error("useGateway must be used inside <Providers gateway={...}>");
  }
  return gateway;
}
