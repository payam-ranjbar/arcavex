/** Public entry point of the gateway module. */

export * from "./ArcavexGateway.ts";
export { FakeArcavexGateway, FAKE_PROJECT_PATH } from "./FakeArcavexGateway.ts";
export type {
  FakeGatewayScript,
  RecordedCall,
  UnversionedDesktopEvent,
} from "./FakeArcavexGateway.ts";
export { DESKTOP_EVENT_CHANNEL, TauriArcavexGateway } from "./TauriArcavexGateway.ts";
