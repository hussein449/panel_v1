import Problem from "@/components/Problem";
import { createCorridorAction } from "@/lib/actions";
import { attempt, getProject } from "@/lib/api";

export const metadata = { title: "New corridor" };

export default async function NewCorridorPage({
  params,
  searchParams,
}: {
  params: { projectId: string };
  searchParams: { error?: string };
}) {
  const project = await attempt(getProject(params.projectId));
  if (!project.ok) return <Problem error={project.error} what="project" />;

  return (
    <div className="shell-page">
      <h1>New corridor</h1>
      <p className="shell-note">in {project.value.name}</p>

      {searchParams.error ? (
        <p className="shell-problem">{searchParams.error}</p>
      ) : null}

      <div className="shell-card">
        <form className="shell-form" action={createCorridorAction}>
          <input type="hidden" name="project_id" value={params.projectId} />

          <label>
            Name
            <input type="text" name="name" required maxLength={200} />
          </label>

          <label>
            Road reference
            <span className="shell-hint">
              As OpenStreetMap knows it — <code>B9</code>, <code>N201</code>. Leave empty
              for a centreline you supply yourself.
            </span>
            <input type="text" name="ref" maxLength={64} />
          </label>

          <fieldset>
            <legend>Bounding box</legend>
            <p className="shell-hint">
              All four or none. The order is the thing that goes wrong, so it is spelled
              out: a box whose south is above its north fetches nothing and returns no
              error, which is why it is refused before it is sent.
            </p>
            <label>
              South
              <input type="number" name="south" step="any" min={-90} max={90} />
            </label>
            <label>
              West
              <input type="number" name="west" step="any" min={-180} max={180} />
            </label>
            <label>
              North
              <input type="number" name="north" step="any" min={-90} max={90} />
            </label>
            <label>
              East
              <input type="number" name="east" step="any" min={-180} max={180} />
            </label>
          </fieldset>

          <label>
            Unit length
            <span className="shell-hint">
              Metres. The corridor is cut into units of this length, and the ranking is
              per unit.
            </span>
            <input
              type="number"
              name="unit_length_m"
              defaultValue={500}
              min={1}
              step="any"
            />
          </label>

          <button type="submit" className="shell-button">
            Create
          </button>
        </form>
      </div>
    </div>
  );
}
