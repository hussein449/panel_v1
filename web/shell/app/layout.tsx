import Link from "next/link";
import type { Metadata } from "next";

// The report's stylesheet, before the shell's own.
//
// Not a copy of its palette: the same file, from the same package, so that a document
// embedded in this app looks like the document that gets emailed. The shell's rules
// come second and add chrome — nothing here restyles the report, and a class in
// `globals.css` that did would be a second renderer arriving one selector at a time.
import "roadrisk-report/styles.css";
import "./globals.css";

import DeploymentBanner from "@/components/DeploymentBanner";

export const metadata: Metadata = {
  title: {
    default: "Road risk",
    template: "%s · Road risk",
  },
  description:
    "Corridor road-risk assessment from open data, with provenance. Every number " +
    "states where it came from, and every refusal is a result rather than an error.",
};

/**
 * The root layout, and the only one.
 *
 * **The banner is here because this is the one place a route cannot opt out of.** Next
 * wraps every page in this file; a page is a child, and a child cannot remove its
 * parent. Put the same component in each page instead and it is on every screen until
 * somebody adds the twelfth, which is the screen it will be missing from.
 *
 * That is the whole of step 5.3b's done-when, and it is asserted in
 * `tests/test_shell.py`: exactly one file in this app renders `<html>`, the banner is
 * rendered here unconditionally, no page imports it, and there is no `pages/` directory
 * to bypass the App Router with.
 *
 * Everything below the banner is chrome and is hidden when the page prints — printing a
 * run must produce the report, and only the report. That is step 4.5's promise, and an
 * app that put its own navigation into somebody's PDF would have broken it.
 */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <DeploymentBanner />
        {/* Assess first, because it is what somebody came here to do. Projects,
            corridors and the job form all still exist and all still work — they are
            the surface for *choosing*, not the surface for starting, so they sit
            behind one word rather than in front of everything. */}
        <nav className="shell-nav shell-chrome" aria-label="Sections">
          <Link className="shell-nav__home" href="/">
            Road risk
          </Link>
          <Link href="/">Assess</Link>
          <Link href="/runs">Runs</Link>
          <Link href="/registry">Registry</Link>
          <Link href="/about">About</Link>
          <Link className="shell-nav__aside" href="/projects">
            Advanced
          </Link>
        </nav>
        <main className="shell-main">{children}</main>
        <footer className="shell-foot shell-chrome">
          <p>
            An assessment states the mode it was produced in, every check that ran,
            every term dropped, and where every number came from. What it cannot support
            is on its own page inside each report, assembled from that run.
          </p>
        </footer>
      </body>
    </html>
  );
}
