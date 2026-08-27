/**
 * The risk colour scale, on its own so that everything drawing risk shares one.
 *
 * **The scale is one hue, light to dark, and it was validated rather than chosen.**
 * Risk is a magnitude, so it gets a sequential ramp — never a rainbow, never a
 * categorical palette pressed into service as a value scale. The six steps below pass
 * the ordinal checks against a white surface: monotone lightness, visible gaps between
 * steps, a hue spread of 18°, and a pale end that still reads as a mark at 2.11:1.
 * Because the ramp varies by lightness it survives being printed in grey.
 *
 * **Why it is a module and not six hex codes in `figures.tsx`.** Step 5.3c draws the
 * same corridor on a MapLibre map, which is a different projection, a different
 * technology and a different file — and if it carried its own copy of these six values,
 * the day somebody adjusted the ramp the screen and the document would disagree about
 * which segment is the dangerous one. That is not a styling inconsistency; it is two
 * answers to the question the product exists to answer.
 *
 * Kept free of React and of the payload types, so that a consumer wanting the scale
 * does not pull the whole report in behind it. `roadrisk-report/risk` is its own export.
 */

/** Sequential, one hue, light→dark. Validated; do not reorder or interpolate. */
export const RISK_RAMP = [
  "#e9a468",
  "#dd8342",
  "#c96323",
  "#a84a13",
  "#84360c",
  "#5e2408",
] as const;

/** Percentile → ramp step. Worst segments get the darkest end. */
export const riskColour = (percentile: number): string =>
  RISK_RAMP[Math.min(RISK_RAMP.length - 1, Math.max(0, Math.floor(percentile * RISK_RAMP.length)))];
