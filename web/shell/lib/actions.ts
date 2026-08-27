"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import {
  createCorridor,
  createProject,
  describeProblem,
  submitJob,
} from "./api";
import type { JobOptions, JobSubmission } from "./wire";

/**
 * The three things this shell can change, as server actions.
 *
 * **The forms work with JavaScript switched off.** A server action posts the form to
 * the server, so every screen here is usable in a browser that runs no script of ours —
 * which is the same standard the report holds itself to, and it is why there is not a
 * single `useState` in this app outside the report component.
 *
 * **A refusal comes back as a query parameter, not as a thrown error.** The API's 422
 * names the column that broke the input contract, and that sentence is the entire value
 * of the refusal; losing it to a generic error page would be worse than not validating
 * at all. Redirecting with the message keeps it, keeps the back button honest, and needs
 * no client state.
 *
 * `redirect` is called *after* the try/catch, never inside it: it works by throwing, and
 * a catch-all around it would swallow the navigation and report it as a failure.
 */

function text(form: FormData, field: string): string {
  const value = form.get(field);
  return typeof value === "string" ? value.trim() : "";
}

function optionalNumber(form: FormData, field: string): number | null {
  const raw = text(form, field);
  return raw === "" ? null : Number(raw);
}

function back(path: string, error: unknown): string {
  return `${path}?error=${encodeURIComponent(describeProblem(error))}`;
}

export async function createProjectAction(form: FormData): Promise<void> {
  let destination: string;
  try {
    const project = await createProject(
      text(form, "name"),
      optionalNumber(form, "spend_cap"),
    );
    revalidatePath("/projects");
    destination = `/projects/${project.id}`;
  } catch (error) {
    destination = back("/projects", error);
  }
  redirect(destination);
}

export async function createCorridorAction(form: FormData): Promise<void> {
  const projectId = text(form, "project_id");
  const here = `/projects/${projectId}/corridors/new`;

  const corners = ["south", "west", "north", "east"].map((corner) =>
    optionalNumber(form, corner),
  );
  const given = corners.filter((corner) => corner !== null);

  if (given.length !== 0 && given.length !== 4) {
    // Refused here rather than sent, because a half-specified box is the one shape the
    // database's own CHECK constraint also refuses — four columns or none.
    redirect(
      back(
        here,
        new Error(
          "A bounding box needs all four of south, west, north and east, or none of " +
            `them. Got ${given.length}.`,
        ),
      ),
    );
  }

  let destination: string;
  try {
    await createCorridor(projectId, {
      name: text(form, "name"),
      ref: text(form, "ref") || null,
      bbox:
        given.length === 4
          ? (corners as [number, number, number, number])
          : null,
      unit_length_m: optionalNumber(form, "unit_length_m") ?? 500,
    });
    revalidatePath(`/projects/${projectId}`);
    destination = `/projects/${projectId}`;
  } catch (error) {
    destination = back(here, error);
  }
  redirect(destination);
}

export async function submitJobAction(form: FormData): Promise<void> {
  const projectId = text(form, "project_id");
  const here = `/projects/${projectId}/jobs/new`;
  const source = text(form, "source");

  const options: Partial<JobOptions> = {
    facility_type: text(form, "facility_type") as JobOptions["facility_type"],
    region: text(form, "region") as JobOptions["region"],
    severity: text(form, "severity") as JobOptions["severity"],
    estimator: text(form, "estimator") as JobOptions["estimator"],
    use_registry_priors: form.get("use_registry_priors") !== null,
    use_spatial: form.get("use_spatial") !== null,
  };

  if (source === "corridor") {
    // Only a real corridor may fetch. A demo centreline is invented, so an adapter run
    // along it would be asking real sources about a road that does not exist — the API
    // refuses that combination at submit, and there is no reason to offer it here.
    options.adapters = form
      .getAll("adapters")
      .filter((value): value is string => typeof value === "string")
      .map((value) => value as NonNullable<JobOptions["adapters"]>[number]);
  }

  const submission: JobSubmission = {
    project_id: projectId,
    demo: source === "demo",
    corridor_id: source === "corridor" ? text(form, "corridor_id") : null,
    panel: null,
    params: options as JobOptions,
  };

  let destination: string;
  try {
    const job = await submitJob(submission);
    revalidatePath(`/projects/${projectId}`);
    destination = `/jobs/${job.id}`;
  } catch (error) {
    destination = back(here, error);
  }
  redirect(destination);
}
