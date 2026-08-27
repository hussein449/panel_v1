/**
 * Step 5.3d — which segment the reader is pointing at, shared by everything that draws one.
 *
 * The report shows the same twenty segments three times over: as a strip along chainage,
 * as a road in plan, and as a ranked table. Until now those three had no idea the others
 * existed, so *this dark band, where is it on the road, and which row is it* was three
 * separate acts of eye-matching. One piece of state fixes it — point at a segment
 * anywhere and it lights up everywhere.
 *
 * **This is an enhancement on top of the document, never a replacement for it.** Every
 * mark keeps its native SVG `<title>`, which is what a browser shows on hover with no
 * JavaScript running at all and what a screen reader announces — and the shell renders
 * the report on the server, so a reader with scripts off receives that markup intact.
 * That is step 5.3d's done-when, and `tools/check_shell.py` fetches the page and counts
 * the titles rather than taking anyone's word for it. Adding a hover handler *in place
 * of* a `<title>` would look better on screen and quietly take the figure away from
 * everybody it was written for.
 *
 * **Nothing moves.** The readout has a reserved height and shows a prompt when nothing is
 * focused, because a document that reflows when you point at it is a document whose
 * printed page is not the page you were reading.
 *
 * **There is no `tabIndex` on the marks, deliberately.** A hundred-and-twenty-unit
 * corridor would put a hundred and twenty tab stops into a document to duplicate numbers
 * that are already in the table beside it — 4.4's own rule is that colour is never the
 * only way to read a value, and the table is what discharges it. What a keyboard or a
 * screen reader gets here is the table and the `<title>`s, and neither is a consolation
 * prize.
 */

import { createContext, useContext, useMemo, useState } from "react";

export interface SegmentFocus {
  /** The unit the reader is pointing at, or null. */
  focused: string | null;
  focus: (unitId: string | null) => void;
}

/**
 * Defaults to a focus that goes nowhere, so a section rendered on its own still works.
 * The library's parts are exported individually and nothing should require a provider to
 * be legible.
 */
const Context = createContext<SegmentFocus>({ focused: null, focus: () => {} });

export function SegmentFocusProvider({ children }: { children: React.ReactNode }) {
  const [focused, setFocused] = useState<string | null>(null);
  const value = useMemo(() => ({ focused, focus: setFocused }), [focused]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export const useSegmentFocus = (): SegmentFocus => useContext(Context);

/**
 * What to spread onto anything standing for one segment — a rect, a polyline, a row.
 *
 * `onMouseLeave` clears rather than leaving the last one lit: a highlight that persists
 * after the pointer has gone is a claim that the reader is still looking at something
 * they are not.
 */
export function segmentHandlers(unitId: string, focus: SegmentFocus["focus"]) {
  return {
    onMouseEnter: () => focus(unitId),
    onMouseLeave: () => focus(null),
  };
}
