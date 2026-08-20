/** Number and text formatting, in one place so the report never disagrees with itself. */

export const count = (value: number): string => value.toLocaleString("en-GB");

export const decimal = (value: number, places = 1): string =>
  value.toLocaleString("en-GB", {
    minimumFractionDigits: places,
    maximumFractionDigits: places,
  });

/**
 * Small rates need significant figures, not decimal places.
 *
 * The threshold for dropping to exponent notation is deliberately low. A crash rate
 * per km-hour is a number like 0.00746, and `7.46e-3` in front of a client reads as
 * physics rather than as road safety.
 */
export const significant = (value: number, digits = 3): string => {
  if (value === 0) return "0";
  const magnitude = Math.abs(value);
  if (magnitude >= 1e-4 && magnitude < 1e6) {
    return Number(value.toPrecision(digits)).toLocaleString("en-GB", {
      maximumSignificantDigits: digits,
      maximumFractionDigits: 20,
    });
  }
  return value.toExponential(digits - 1);
};

export const percent = (share: number, places = 0): string =>
  `${(share * 100).toFixed(places)}%`;

export const metres = (value: number): string => `${count(Math.round(value))} m`;

/** A chainage span, the way a road engineer writes one. */
export const extent = (start?: number, end?: number): string | null => {
  if (start === undefined || end === undefined) return null;
  return `${count(Math.round(start))}–${count(Math.round(end))} m`;
};

export const signed = (value: number, places = 4): string =>
  `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(places)}`;

/**
 * Trim a citation for a table cell without hiding that it was trimmed.
 *
 * The untruncated source stays on the element's `title`, so nothing in the report is
 * unreachable — it is one hover away rather than gone.
 */
export const shorten = (text: string, limit = 90): string =>
  text.length <= limit ? text : `${text.slice(0, limit - 1).trimEnd()}…`;
