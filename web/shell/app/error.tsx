"use client";

/**
 * The last resort, not the plan.
 *
 * Every page here catches its own problems and renders them with the words the API
 * used, because a production build replaces an uncaught server error with a digest and
 * nothing else. This catches what none of them anticipated, and its whole job is to not
 * be a blank white page — the same job `Boundary` does inside the report.
 *
 * The banner above it survives, because it is in the layout and a layout is not
 * unmounted by an error in a page.
 */
export default function ShellError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="shell-page">
      <div className="shell-card">
        <h2>This screen did not render</h2>
        <p className="shell-problem">{error.message || "No message was given."}</p>
        {error.digest ? (
          <p className="shell-note">
            The server logged this as <code>{error.digest}</code>. A production build
            deliberately keeps the detail out of the page; the log has it.
          </p>
        ) : null}
        <p>
          <button type="button" className="shell-button" onClick={() => reset()}>
            Try again
          </button>
        </p>
      </div>
    </div>
  );
}
