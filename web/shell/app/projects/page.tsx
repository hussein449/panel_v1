import Link from "next/link";

import Problem from "@/components/Problem";
import { createProjectAction } from "@/lib/actions";
import { attempt, listProjects } from "@/lib/api";
import { when } from "@/lib/format";

export const metadata = { title: "Projects" };

/**
 * Every project this tenant has, and the form that makes another.
 *
 * A project is a body of work — usually one road authority's network, or one study —
 * and it is what corridors, jobs and runs hang from. It also carries the spend cap that
 * step 5.2b enforces before the call that would breach it, which is why the field is
 * here now rather than arriving with the accounting.
 */
export default async function ProjectsPage({
  searchParams,
}: {
  searchParams: { error?: string };
}) {
  const projects = await attempt(listProjects());

  return (
    <div className="shell-page">
      <h1>Projects</h1>

      {searchParams.error ? (
        <p className="shell-problem">{searchParams.error}</p>
      ) : null}

      {projects.ok ? (
        <div className="shell-card">
          {projects.value.length === 0 ? (
            <p className="shell-empty">
              No projects yet. The form below makes the first one.
            </p>
          ) : (
            <table className="shell-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Spend cap</th>
                  <th>Created</th>
                  <th>Id</th>
                </tr>
              </thead>
              <tbody>
                {projects.value.map((project) => (
                  <tr key={project.id}>
                    <td>
                      <Link href={`/projects/${project.id}`}>{project.name}</Link>
                    </td>
                    <td>
                      {project.spend_cap === null ? (
                        <span className="shell-empty">uncapped</span>
                      ) : (
                        project.spend_cap
                      )}
                    </td>
                    <td>{when(project.created_at)}</td>
                    <td className="shell-mono">{project.id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : (
        <Problem error={projects.error} what="projects" />
      )}

      <div className="shell-card">
        <h2>New project</h2>
        <form className="shell-form" action={createProjectAction}>
          <label>
            Name
            <input type="text" name="name" required maxLength={200} />
          </label>
          <label>
            Spend cap
            <span className="shell-hint">
              Whole currency units, or empty for uncapped. Nothing counts spend yet —
              step 5.2b puts the accounting behind this and refuses the call that would
              breach it, rather than reporting the breach afterwards.
            </span>
            <input type="number" name="spend_cap" min={0} step="0.01" />
          </label>
          <button type="submit" className="shell-button">
            Create
          </button>
        </form>
      </div>
    </div>
  );
}
