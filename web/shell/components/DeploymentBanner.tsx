import { getHealth, TENANT_ENV } from "@/lib/api";

/**
 * What this deployment is, on every screen, from the root layout.
 *
 * **This is step 5.3b's done-when.** The banner is a *layout* element and not a
 * component pages remember to include, because "remember to include it" is how it comes
 * off the one screen where it mattered. `tests/test_shell.py` asserts the arrangement
 * rather than trusting it: one root layout, the banner rendered there unconditionally,
 * and no page importing it — so there is no route that can be added without it, and
 * nothing to forget.
 *
 * It is rendered on the server, so it is in the HTML rather than painted by JavaScript,
 * and it survives a reader with scripts off. There is no dismiss control, and that is
 * not an oversight: every sentence in here is a thing somebody would otherwise discover
 * by watching a job never finish, or by assuming a header is a credential.
 *
 * **Every line is read off `GET /health`, not written in.** When 5.4a puts real
 * identities behind the tenant header, `auth` stops being null and this stops saying
 * the deployment is unauthenticated — without anybody editing this file. A banner whose
 * warnings are hard-coded is a banner that is eventually wrong in the reassuring
 * direction.
 *
 * The other banner in this app is the *mode* banner over a run — `A-full`, `B`, the
 * rung — which is a property of an assessment rather than of a deployment and lives in
 * the run segment's own layout. Neither can be omitted, and they are not the same fact.
 */
export default async function DeploymentBanner() {
  const deployment = await getHealth();

  if (!deployment.reachable) {
    return (
      <aside
        className="shell-banner shell-banner--alarm shell-chrome"
        aria-label="What this deployment is"
      >
        <p className="shell-banner__lead">
          <span className="shell-banner__dot" aria-hidden="true" />
          This shell cannot reach the API. Nothing on any screen is live.
        </p>
        <ul className="shell-banner__facts">
          <li>
            <code>{deployment.url}</code> did not answer: {deployment.reason}.
          </li>
          <li>
            Start it with <code>roadrisk serve</code>, or point{" "}
            <code>$ROADRISK_API_URL</code> at one that is running.
          </li>
        </ul>
      </aside>
    );
  }

  const { health, url, tenant } = deployment;
  const facts: React.ReactNode[] = [];

  if (health.auth === null) {
    facts.push(
      <>
        <strong>Not authenticated.</strong> <code>X-Tenant-Id</code> scopes which rows
        exist; it does not prove who you are. Anyone who can reach this service can read
        this tenant&rsquo;s runs. Step 5.4a replaces it with identities and row-level
        policies in the database.
      </>,
    );
  } else {
    facts.push(
      <>
        <strong>Identities:</strong> {health.auth}.
      </>,
    );
  }

  if (health.runner === null) {
    facts.push(
      <>
        <strong>Nothing executes jobs here.</strong> A job submitted to this deployment
        is stored and queued, and will stay <code>queued</code>. This is a service that
        serves runs somebody else produced.
      </>,
    );
  } else if (health.runner === "in-process") {
    facts.push(
      <>
        <strong>Jobs run inside the API process.</strong> Work in flight does not
        survive a restart — a job orphaned that way is reclaimed and run again, not
        lost, but there is no queue and no second machine. Step 5.2a is the worker.
      </>,
    );
  } else {
    facts.push(
      <>
        <strong>Jobs run on {health.runner}.</strong>
      </>,
    );
  }

  if (!tenant) {
    facts.push(
      <>
        <strong>No tenant is configured</strong>, so this shell can see no rows at all.
        Set <code>${TENANT_ENV}</code> to the id printed by{" "}
        <code>roadrisk store new-tenant</code>.
      </>,
    );
  }

  if (!health.artefacts_available) {
    facts.push(
      <>
        Artefact download is off — <code>$ROADRISK_ARTEFACT_ROOT</code> is unset, so the
        files a run wrote cannot be served. The run itself is unaffected.
      </>,
    );
  }

  const tone = health.auth === null || health.runner === null ? "warn" : "ok";

  return (
    <aside
      className={`shell-banner shell-banner--${tone} shell-chrome`}
      aria-label="What this deployment is"
    >
      <p className="shell-banner__lead">
        <span className="shell-banner__dot" aria-hidden="true" />
        Read this before you read anything else on this screen
      </p>
      <ul className="shell-banner__facts">
        {facts.map((fact, index) => (
          <li key={index}>{fact}</li>
        ))}
      </ul>
      <p className="shell-banner__meta">
        <code>{url}</code> · engine v{health.engine_version} · payload schema{" "}
        {health.schema_version} · registry {health.registry_version}
        {tenant ? (
          <>
            {" "}
            · tenant <code>{tenant.slice(0, 8)}</code>
          </>
        ) : null}
      </p>
    </aside>
  );
}
