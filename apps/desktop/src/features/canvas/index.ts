export { CanvasViewport, type CanvasViewportProps } from "./CanvasViewport.tsx";
export { SelectionOverlay, type SelectionOverlayProps } from "./SelectionOverlay.tsx";
export {
  IDLE,
  reduce,
  selectionRect,
  handleFor,
  HANDLES,
  type BoxPt,
  type HandleName,
  type InteractionEvent,
  type InteractionState,
  type PointerTarget,
} from "./interactionMachine.ts";
export { pointerToCanvas, deltaToCanvas, lengthToCanvas, lengthToCss } from "./coordinates.ts";
export { canvasGuides, guidesFromRects, mergeGuides } from "./snapping.ts";
