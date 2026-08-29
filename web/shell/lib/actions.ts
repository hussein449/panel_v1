"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import {
  createCorridor,
  createProject,
  describeProblem,
  listProjects,
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

// -- the landing flow ----------------------------------------------------------

/**
 * Where runs made from the front page are filed.
 *
 * A project is a real object with a spend cap on it and it is not going away — but it is
 * not a question somebody arriving with a road in mind can answer, and asking it first
 * was most of what made this product feel like paperwork. So one is found or made, and
 * the reader meets projects when they go looking for them under *Advanced*.
 */
const DEFAULT_PROJECT = "Assessments";

async function defaultProject(): Promise<string> {
  const existing = await listProjects();
  const found = existing.find((project) => project.name === DEFAULT_PROJECT);
  return (found ?? (await createProject(DEFAULT_PROJECT, null))).id;
}

/**
 * The whole of the front page, as one submission: road in, job out.
 *
 * **The crash CSV is parsed here rather than in the browser.** Everything else on this
 * app works with JavaScript switched off, and a file input posts perfectly well without
 * it; parsing on the client would also put a piece of the input contract in the
 * frontend, where the 4.7 defect came from. What the parser does *not* do is validate:
 * the API refuses a table that could never be snapped and names the column, and a second
 * opinion here could only disagree with it.
 */
export async function assessRoadAction(form: FormData): Promise<void> {
  const key = text(form, "selector_key");
  const value = text(form, "selector_value");
  const label = text(form, "label") || value;

  if (key === "" || value === "") {
    redirect(back("/", new Error("Pick a road on the map first.")));
  }

  const corners = ["south", "west", "north", "east"].map((corner) =>
    optionalNumber(form, corner),
  );
  if (corners.some((corner) => corner === null || Number.isNaN(corner))) {
    redirect(
      back(
        "/",
        new Error(
          "The map did not report an area to search in. Move the map once and try again.",
        ),
      ),
    );
  }

  let destination: string;
  try {
    const crashes = await readCrashCsv(form.get("crashes"));
    const projectId = await defaultProject();

    const corridor = await createCorridor(projectId, {
      name: label,
      ref: key === "ref" ? value : null,
      osm_name: key === "name" ? value : null,
      bbox: corners as [number, number, number, number],
      unit_length_m: 500,
    });

    const submission: JobSubmission = {
      project_id: projectId,
      corridor_id: corridor.id,
      panel: null,
      demo: false,
      crashes,
      params: {
        // **On by default, and the reason is not convenience.** Without OSM the panel
        // carries the two factors geometry alone can produce, and the assessment is
        // nearly empty. The job form under Advanced leaves every adapter off because
        // that screen is for someone choosing; this one is for someone who wants their
        // road assessed.
        //
        // `imagery` is off unless asked for: it is a second network round trip and it
        // needs a Mapillary token the deployment may not have. It fills no factor —
        // it answers whether anybody has driven this road, which is the question the
        // A10 raised and nothing could answer.
        adapters: form.get("check_imagery") !== null ? ["osm", "imagery"] : ["osm"],

        // **The context the weights are selected against, and its omission was
        // expensive.** This action used to send adapters and nothing else, so all three
        // fell back to `any` / `global` / `all` — under which only weights declaring no
        // scope at all are admissible. A real corridor came back with eleven factors
        // measured at full coverage and exactly one of them scored, and nothing on the
        // screen connected those two facts, because the screen never asked. Passed
        // through as sent: these are enums the API validates, and a bad one should be
        // its 422 naming the field rather than a default quietly chosen here.
        facility_type: text(form, "facility_type") || "any",
        region: text(form, "region") || "global",
        severity: text(form, "severity") || "all",
      } as JobOptions,
    };

    const job = await submitJob(submission);
    revalidatePath("/runs");
    destination = `/jobs/${job.id}`;
  } catch (error) {
    destination = back("/", error);
  }
  redirect(destination);
}

/**
 * A crash CSV as the rows the API takes, or null when no file was chosen.
 *
 * Deliberately small. It reads the three columns the input contract names and passes
 * every other column through untouched, because the pipeline takes column names as
 * arguments and a parser that renamed things here would be holding a second opinion
 * about a contract that already has one. Quoted fields are handled because address-like
 * columns routinely contain commas; anything more elaborate belongs in a library, and
 * this file should not grow one for a format this narrow.
 */
async function readCrashCsv(file: FormDataEntryValue | null) {
  if (!file || typeof file === "string" || file.size === 0) return null;

  const text = await file.text();
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== "");
  if (lines.length < 2) {
    throw new Error(
      `${file.name} has no rows under its header. A crash file needs one row per crash.`,
    );
  }

  const header = splitCsvLine(lines[0]).map((cell) => cell.trim().toLowerCase());
  return lines.slice(1).map((line, index) => {
    const cells = splitCsvLine(line);
    if (cells.length !== header.length) {
      throw new Error(
        `${file.name} line ${index + 2} has ${cells.length} value(s) where the header ` +
          `has ${header.length}. A stray comma inside an unquoted field is the usual cause.`,
      );
    }
    const row: Record<string, unknown> = {};
    header.forEach((column, position) => {
      const raw = cells[position].trim();
      // Numbers where the API expects numbers, and the raw string everywhere else. A
      // latitude arriving as "34.9" is a 422 about a coordinate that is not a number,
      // which is a confusing way to be told about a CSV.
      row[column] =
        column === "latitude" || column === "longitude"
          ? raw === ""
            ? raw
            : Number(raw)
          : raw;
    });
    return row;
  });
}

/** One CSV line, honouring double-quoted fields and `""` as an escaped quote. */
function splitCsvLine(line: string): string[] {
  const cells: string[] = [];
  let cell = "";
  let quoted = false;

  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (quoted) {
      if (character === '"') {
        if (line[index + 1] === '"') {
          cell += '"';
          index += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += character;
      }
    } else if (character === '"') {
      quoted = true;
    } else if (character === ",") {
      cells.push(cell);
      cell = "";
    } else {
      cell += character;
    }
  }
  cells.push(cell);
  return cells.map((value) => value.replace(/^﻿/, ""));
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
