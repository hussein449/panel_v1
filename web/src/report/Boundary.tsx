import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

/**
 * A rendering failure must not become an empty page.
 *
 * React unmounts the whole tree on an uncaught error, so without this one bad value in
 * one figure erases the entire report — every number, every receipt, every licence —
 * and leaves white. Nothing about that tells the reader what happened or that the data
 * is intact. This holds the failure to a message, names it, and says where the same
 * numbers are.
 *
 * It lives in the library rather than in an entry point because **both entries need
 * it, and for the same reason**. It moved here at step 5.3a: while there was one entry
 * it could sit next to the mounting code without anybody noticing the difference, and
 * the moment there were two, leaving it there would have meant either writing it twice
 * or shipping one surface that fails silently to white.
 */
export class Boundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("The report failed to render.", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="fallback">
        <h1>This report could not be drawn</h1>
        <p>
          The assessment itself is intact — it is stored in this file and in the JSON
          beside it. Only the page that draws it failed.
        </p>
        <p className="caveat caveat--strong">{String(this.state.error.message)}</p>
        <p className="fallback__note">
          The same numbers are in <code>assessment.json</code>,{" "}
          <code>corridor.json</code> and <code>ranking.csv</code> in the same folder.
          Please report the message above with the run.
        </p>
      </div>
    );
  }
}
