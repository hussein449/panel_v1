/**
 * The closing judgement: what this assessment is worth, and what it found.
 *
 * **It grades the assessment, not the road.** A safety rating — "this corridor is a C" —
 * would need corridors scored against each other on a common scale, and this engine
 * fits one road at a time from that road's own crashes. Two runs are not comparable
 * quantities, so a letter grade over them would be invented rather than measured, and
 * it would be the single most quotable number in the document.
 *
 * What can be said honestly is three things, and this module derives all three from the
 * payload rather than from anything the caller passes in:
 *
 * 1. **How much weight the assessment carries** — the mode it reached, whether it
 *    predicted road it had not seen, and whether anything material stands against it.
 * 2. **What it found** — the strongest term that cleared significance, or plainly that
 *    none did.
 * 3. **Where the crashes actually are** — concentration along the corridor, which is a
 *    statement about the road and needs no model at all to be true.
 *
 * Nothing here recomputes statistics. Every number is read off the run, so the verdict
 * cannot drift from the sections above it.
 */

import type { Assessment, Coefficient, Limitation, Run } from "./types";

/** How much weight the assessment carries. Ordered best to worst. */
export type Standing = "strong" | "qualified" | "provisional" | "ranking";

export interface Verdict {
  standing: Standing;
  /** One line, the headline of the whole document. */
  headline: string;
  /** Why it got that standing, as separate clauses a reader can check. */
  because: string[];
  /** The strongest significant term, or null when nothing cleared. */
  finding: Coefficient | null;
  /** Where to send somebody, if the ranking produced a blackspot. */
  where: {
    label: string;
    observed: number | null;
    shareOfCrashes: number | null;
    shareOfLength: number | null;
  } | null;
  /** What would move the standing up, or null when it is already at the top. */
  next: string | null;
}

const STANDING_LABEL: Record<Standing, string> = {
  strong: "Sound",
  qualified: "Sound, with qualifications",
  provisional: "Provisional",
  ranking: "Ranking only",
};

export const standingLabel = (standing: Standing): string => STANDING_LABEL[standing];

/**
 * The finding a reader should act on: the most confident term that agrees with the
 * literature.
 *
 * **Not the largest coefficient**, which is the obvious wrong answer. Each factor
 * enters on its own transformed scale — `ln(lanes)` spans about 0.7 to 1.6 on a
 * motorway, `ln1p(accesses per km)` spans something else entirely — so their estimates
 * are not on a common ruler and "biggest" compares nothing. On the A3 that rule picked
 * `lanes` at +1.21 over `access_density` at +0.36, when `lanes` is the term the model
 * itself flags as standing in for traffic volume.
 *
 * The p-value *is* comparable across terms, so confidence orders them honestly.
 *
 * **And a term the sign guard has flagged is excluded outright**, however confident.
 * A coefficient pointing against the evidence is explicitly not interpretable as a
 * cause — the guard says so in its own verdict — so presenting one here as "what it
 * found" would contradict the section above it.
 */
function strongestFinding(assessment: Assessment): Coefficient | null {
  const contradicting = new Set(
    (assessment.sign_guard?.findings ?? [])
      .filter((f) => f.contradicts)
      .map((f) => f.factor),
  );
  const terms = (assessment.fit?.coefficients ?? []).filter(
    (c) =>
      typeof c.p_value === "number" &&
      c.p_value < 0.05 &&
      !contradicting.has(c.factor),
  );
  if (terms.length === 0) return null;
  return terms.reduce((best, c) => (c.p_value < best.p_value ? c : best));
}

export function buildVerdict(run: Run): Verdict {
  const { assessment, corridor } = run;
  const limitations: Limitation[] = run.limitations ?? [];
  const material = limitations.filter((l) => l.severity === "material");
  const validated = assessment.validation?.passed === true;
  const hardFailure = assessment.checks.some(
    (c) => c.status === "failed" && c.failure_type === "HARD",
  );
  const modeA = assessment.mode === "A";

  // Mode B is its own standing rather than a poor grade of Mode A: it is a ranking
  // from published weights, and calling it "provisional" would imply that more of the
  // same kind of evidence would promote it. It would not — only crashes would.
  let standing: Standing;
  if (!modeA) standing = "ranking";
  else if (hardFailure) standing = "provisional";
  else if (validated && material.length === 0) standing = "strong";
  else if (validated || material.length === 0) standing = "qualified";
  else standing = "provisional";

  const because: string[] = [];
  if (modeA) {
    because.push(
      `Fitted from this corridor's own ${assessment.panel.total_crashes.toLocaleString("en-GB")} crashes at ${assessment.rung}.`,
    );
  } else {
    because.push(
      "No model was fitted. Segments are scored from published weights, which ranks them against each other and does not estimate how many crashes to expect.",
    );
  }
  if (assessment.validation?.available) {
    because.push(
      validated
        ? "It predicted stretches of road held back from it, within the tolerance the HSM treats as ordinary calibration."
        : "It did not reproduce stretches of road held back from it, so treat the ranking as indicative and the counts as weak.",
    );
  }
  because.push(
    material.length === 0
      ? "Nothing material stands against it."
      : `${material.length} material limitation${material.length === 1 ? "" : "s"} stand against it, set out below.`,
  );

  // Chainage is optional on a blackspot — a panel supplied without geography ranks
  // segments but cannot say where they are — so every field below is guarded and the
  // verdict degrades to naming the worst unit rather than inventing a position.
  const blackspot = assessment.ranking?.blackspots?.[0] ?? null;
  const totalCrashes = assessment.panel.total_crashes || null;
  const corridorLength = corridor?.corridor.length_m ?? null;
  const num = (v: number | null | undefined): v is number =>
    typeof v === "number" && Number.isFinite(v);

  const where = blackspot
    ? {
        label:
          num(blackspot.start_m) && num(blackspot.end_m)
            ? `${Math.round(blackspot.start_m).toLocaleString("en-GB")}–${Math.round(blackspot.end_m).toLocaleString("en-GB")} m`
            : blackspot.worst_unit,
        observed: num(blackspot.observed) ? blackspot.observed : null,
        shareOfCrashes:
          totalCrashes && num(blackspot.observed)
            ? blackspot.observed / totalCrashes
            : null,
        shareOfLength:
          corridorLength && num(blackspot.length_m)
            ? blackspot.length_m / corridorLength
            : null,
      }
    : null;

  const finding = modeA ? strongestFinding(assessment) : null;

  const span = blackspot && num(blackspot.length_m) ? blackspot.length_m / 1000 : null;
  const headline =
    where && num(where.observed) && span
      ? `The worst ${span.toFixed(1)} km of this corridor carries ${where.observed.toLocaleString("en-GB")} of its ${assessment.panel.total_crashes.toLocaleString("en-GB")} crashes.`
      : where
        ? `${where.label} ranks worst of ${(assessment.ranking?.n_units ?? 0).toLocaleString("en-GB")} segments.`
        : "This corridor produced no concentration worth singling out.";

  let next: string | null = null;
  if (standing === "ranking") {
    next = "Supply a crash table for this corridor. Nothing else promotes a ranking into an estimate.";
  } else if (!validated && assessment.validation?.available) {
    next =
      "The model does not yet predict road it has not seen. More crashes, or a specification that generalises, is what closes that.";
  } else if (material.length > 0) {
    next = `Resolve the material limitation${material.length === 1 ? "" : "s"} below and re-run.`;
  }

  return { standing, headline, because, finding, where, next };
}
