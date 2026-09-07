/**
 * The selection chrome: bounds, eight resize handles, a rotate handle, and marquee.
 *
 * Drawn in CSS pixels over the raster, never into it. Handles keep a constant on-screen size at
 * any zoom — a handle that scaled with the canvas would become ungrabbable when zoomed out and
 * cover the layer when zoomed in.
 */

import type { ReactNode } from "react";

import { HANDLES, handleFor, type BoxPt, type HandleName } from "./interactionMachine.ts";
import { lengthToCss } from "./coordinates.ts";
import type { Viewport } from "./selection.ts";

/** On-screen handle size in CSS pixels, independent of zoom. */
export const HANDLE_SIZE_CSS = 9;
/** How far above the box the rotate handle sits, in CSS pixels. */
export const ROTATE_OFFSET_CSS = 22;

export interface SelectionOverlayProps {
  readonly box: BoxPt | null;
  readonly viewport: Viewport;
  /** Marquee rectangle while dragging on the background. */
  readonly marquee: BoxPt | null;
  readonly editable: boolean;
  readonly onHandlePointerDown: (
    handle: HandleName,
    event: React.PointerEvent<HTMLElement>,
  ) => void;
  readonly onRotatePointerDown: (event: React.PointerEvent<HTMLElement>) => void;
}

function toCss(box: BoxPt, viewport: Viewport) {
  return {
    left: box.x * viewport.scale + viewport.panXCss,
    top: box.y * viewport.scale + viewport.panYCss,
    width: lengthToCss(box.w, viewport),
    height: lengthToCss(box.h, viewport),
  };
}

export function SelectionOverlay({
  box,
  viewport,
  marquee,
  editable,
  onHandlePointerDown,
  onRotatePointerDown,
}: SelectionOverlayProps): ReactNode {
  return (
    <>
      {marquee ? (
        <div className="overlay__marquee" style={toCss(marquee, viewport)} aria-hidden="true" />
      ) : null}
      {box ? (
        <div className="overlay__selection" style={toCss(box, viewport)} aria-hidden="true" />
      ) : null}
      {box && editable
        ? HANDLES.map((handle) => {
            const point = handleFor(handle, box);
            return (
              <button
                key={handle}
                type="button"
                className="overlay__handle"
                data-handle={handle}
                aria-label={`Resize ${handle}`}
                style={{
                  left: point.x * viewport.scale + viewport.panXCss - HANDLE_SIZE_CSS / 2,
                  top: point.y * viewport.scale + viewport.panYCss - HANDLE_SIZE_CSS / 2,
                  width: HANDLE_SIZE_CSS,
                  height: HANDLE_SIZE_CSS,
                }}
                onPointerDown={(event) => onHandlePointerDown(handle, event)}
              />
            );
          })
        : null}
      {box && editable ? (
        <button
          type="button"
          className="overlay__rotate"
          aria-label="Rotate selection"
          style={{
            left: (box.x + box.w / 2) * viewport.scale + viewport.panXCss - HANDLE_SIZE_CSS / 2,
            top: box.y * viewport.scale + viewport.panYCss - ROTATE_OFFSET_CSS,
            width: HANDLE_SIZE_CSS,
            height: HANDLE_SIZE_CSS,
          }}
          onPointerDown={onRotatePointerDown}
        />
      ) : null}
    </>
  );
}
