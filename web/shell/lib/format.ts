/**
 * The shell's formatters.
 *
 * Deliberately few. The report library has its own — every one of them written to
 * survive a null, because the payload has them — and this is chrome around a document,
 * not a second renderer. Anything here that started formatting a *number out of a run*
 * would be the beginning of a second report.
 */

/**
 * A timestamp as a person reads one, in UTC.
 *
 * UTC and not the reader's zone: this renders on the server, and a server-rendered
 * local time is the *server's* local time wearing the reader's name. The run's own
 * timestamps inside the report are handled by the report.
 */
export function when(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

/** The head of a UUID — enough to recognise a row, short enough to read in a table. */
export function shortId(value: string | null | undefined): string {
  return value ? value.slice(0, 8) : "—";
}

/** `500` → `500 m`, `null` → `—`. */
export function metres(value: number | null | undefined): string {
  return value == null ? "—" : `${value.toLocaleString("en-GB")} m`;
}

/**
 * A bounding box as `south, west, north, east`, in the order the API takes it.
 *
 * Spelled out rather than abbreviated because the order is the thing that gets it
 * wrong, and a corridor fetched from an inverted box is an empty result rather than an
 * error.
 */
export function bbox(
  value: [number, number, number, number] | null | undefined,
): string {
  return value ? value.map((degree) => degree.toFixed(4)).join(", ") : "—";
}
