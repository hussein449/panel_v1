import { ApiRefusal, ApiUnreachable, TenantNotConfigured, TENANT_ENV } from "@/lib/api";

/**
 * Something did not come back, said in the words of the thing that refused it.
 *
 * The API's refusal contract makes three outcomes distinct — a panel that breaks the
 * input contract, an assessment that descended to Mode B, and infrastructure failing —
 * and the first thing a front end usually does is collapse them back into *something
 * went wrong*. Only one of them reaches this component at all: a Mode B descent is a
 * finished run and is drawn as one, and a contract violation arrives here carrying the
 * column that caused it, which is the entire value of that refusal.
 */
export default function Problem({
  error,
  what,
}: {
  error: unknown;
  what: string;
}) {
  if (error instanceof TenantNotConfigured) {
    return (
      <div className="shell-card">
        <h2>This shell has no tenant</h2>
        <p>
          Every row in this service belongs to a tenant, and there is no login yet, so
          the tenant comes from the environment of the process serving this page.
        </p>
        <pre className="shell-mono">
          {`roadrisk store new-tenant "my road authority"\nexport ${TENANT_ENV}=<the id it printed>`}
        </pre>
        <p className="shell-note">
          Restart this app afterwards. Until then it can show you the registry and this
          deployment&rsquo;s own state, and nothing that belongs to anybody.
        </p>
      </div>
    );
  }

  if (error instanceof ApiUnreachable) {
    return (
      <div className="shell-card">
        <h2>The API did not answer</h2>
        <p className="shell-problem">{error.message}</p>
        <p>
          This app renders every screen from that service. Start it with{" "}
          <code>roadrisk serve</code>, or set <code>$ROADRISK_API_URL</code> to one that
          is running.
        </p>
      </div>
    );
  }

  if (error instanceof ApiRefusal && error.status === 404) {
    return (
      <div className="shell-card">
        <h2>No such {what}</h2>
        <p className="shell-problem">{error.message}</p>
        <p className="shell-note">
          A tenant that does not own a row cannot see it, and an unknown tenant is not an
          error — it is a tenant with no rows, which is what tenancy means. So this page
          reads the same whether the row never existed or belongs to somebody else.
        </p>
      </div>
    );
  }

  if (error instanceof ApiRefusal) {
    return (
      <div className="shell-card">
        <h2>Refused</h2>
        <p className="shell-problem">
          <strong>{error.code}</strong> — {error.message}
          {error.field ? (
            <>
              {" "}
              (<code>{error.field}</code>)
            </>
          ) : null}
        </p>
        <p className="shell-note">
          A refusal is a result. Nothing was half-done: a submission refused at the
          boundary created no job, and there is nothing here to clean up.
        </p>
      </div>
    );
  }

  return (
    <div className="shell-card">
      <h2>Could not load the {what}</h2>
      <p className="shell-problem">
        {error instanceof Error ? error.message : String(error)}
      </p>
    </div>
  );
}
