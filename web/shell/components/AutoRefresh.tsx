"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

/**
 * Ask the server for this screen again, every few seconds, while a job is in flight.
 *
 * The one thing in this app that needs JavaScript, and the page it sits on works
 * without it: there is a *Check again* link beside it that does the same thing with a
 * click. Polling is what a client has to do here — `POST /jobs` returns 202 because a
 * cold corridor is around a minute and a Bayesian fit is tens of them, and no HTTP
 * request survives that.
 *
 * `router.refresh()` re-renders the server components in place rather than reloading
 * the document, so the banner above does not flash and the scroll position is kept.
 */
export default function AutoRefresh({ seconds }: { seconds: number }) {
  const router = useRouter();

  useEffect(() => {
    const timer = setInterval(() => router.refresh(), seconds * 1000);
    return () => clearInterval(timer);
  }, [router, seconds]);

  return null;
}
