/**
 * Number and text formatting, in one place so the report never disagrees with itself.
 *
 * **Every formatter takes `number | null | undefined` and every one of them survives
 * it.** That is not defensive habit — the payload legitimately contains nulls. A
 * quantity the engine could not compute (a mean deviation over folds that produced
 * nothing, a calibration factor with no denominator) arrives as `null`, because that
 * is what JSON has for "no value". A formatter that assumed a number there would
 * throw, and one uncaught throw in React unmounts the entire tree — turning one
 * missing diagnostic into a blank report.
 */

/** What an absent value looks like. An en dash, not a zero: they mean different things. */
export const ABSENT = "–";

const present = (value: number | null | undefined): value is number =>
  typeof value === "number" && Number.isFinite(value);

export const count = (value: number | null | undefined): string =>
  present(value) ? value.toLocaleString("en-GB") : ABSENT;

export const decimal = (value: number | null | undefined, places = 1): string =>
  present(value)
    ? value.toLocaleString("en-GB", {
        minimumFractionDigits: places,
        maximumFractionDigits: places,
      })
    : ABSENT;

/**
 * Small rates need significant figures, not decimal places.
 *
 * The threshold for dropping to exponent notation is deliberately low. A crash rate
 * per km-hour is a number like 0.00746, and `7.46e-3` in front of a client reads as
 * physics rather than as road safety.
 */
export const significant = (value: number | null | undefined, digits = 3): string => {
  if (!present(value)) return ABSENT;
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

export const percent = (
  share: number | null | undefined,
  places = 0,
): string => (present(share) ? `${(share * 100).toFixed(places)}%` : ABSENT);

export const metres = (value: number | null | undefined): string =>
  present(value) ? `${count(Math.round(value))} m` : ABSENT;

/** A chainage span, the way a road engineer writes one. */
export const extent = (
  start: number | null | undefined,
  end: number | null | undefined,
): string | null => {
  if (!present(start) || !present(end)) return null;
  return `${count(Math.round(start))}–${count(Math.round(end))} m`;
};

export const signed = (value: number | null | undefined, places = 4): string =>
  present(value)
    ? `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(places)}`
    : ABSENT;

/**
 * Trim a citation for a table cell without hiding that it was trimmed.
 *
 * The untruncated source stays on the element's `title`, so nothing in the report is
 * unreachable — it is one hover away rather than gone.
 */
export const shorten = (text: string, limit = 90): string =>
  text.length <= limit ? text : `${text.slice(0, limit - 1).trimEnd()}…`;
