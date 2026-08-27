import Problem from "@/components/Problem";
import { attempt, getRegistry } from "@/lib/api";

export const metadata = { title: "Registry" };

/**
 * Every declared factor, with the tier and licence of each way to obtain it.
 *
 * One of two screens that work with no tenant configured, because it describes the
 * service rather than anybody's rows.
 *
 * **`sourced` is the column worth reading.** A factor that carries no cited weight is
 * not silently weighted zero — it never enters Mode B at all, and the report names it.
 * The obligation column is the other one: a licence that requires credit is a thing a
 * client owes the people whose data produced their ranking, and it is stated here for
 * the same reason it is stated in every report.
 */
export default async function RegistryPage() {
  const registry = await attempt(getRegistry());
  if (!registry.ok) return <Problem error={registry.error} what="registry" />;

  const { value } = registry;

  return (
    <div className="shell-page">
      <h1>Factor registry</h1>
      <p>
        Version {value.version} · {value.factor_count} factors, {value.sourced_count}{" "}
        with cited weights · read from <code>{value.source}</code>
      </p>
      <p className="shell-note">
        The hash is the file&rsquo;s: <code className="shell-mono">{value.sha256}</code>.
        A run&rsquo;s manifest carries the hash of the registry it was assessed under, so
        comparing the two is the only honest way to answer <em>is this still current</em>.
      </p>

      <div className="shell-card">
        <h2>Tiers</h2>
        <table className="shell-table">
          <tbody>
            {value.tiers.map((tier) => (
              <tr key={tier.code}>
                <th>{tier.code}</th>
                <td>{tier.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="shell-card">
        <h2>Licences</h2>
        <table className="shell-table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Credit</th>
              <th>Share-alike</th>
              <th>What it obliges</th>
            </tr>
          </thead>
          <tbody>
            {value.licences.map((licence) => (
              <tr key={licence.code}>
                <td className="shell-mono">{licence.code}</td>
                <td>{licence.credit_required ? "required" : "—"}</td>
                <td>{licence.share_alike_database ? "database" : "—"}</td>
                <td>{licence.obligation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="shell-card">
        <h2>Factors</h2>
        <table className="shell-table">
          <thead>
            <tr>
              <th>Factor</th>
              <th>Transform</th>
              <th>Sign</th>
              <th>Drop</th>
              <th>Weights</th>
              <th>Sources</th>
            </tr>
          </thead>
          <tbody>
            {value.factors.map((factor) => (
              <tr key={factor.name}>
                <td>
                  <strong>{factor.label}</strong>
                  <br />
                  <span className="shell-mono">{factor.column}</span>
                </td>
                <td>{factor.transform}</td>
                <td>{factor.expected_sign}</td>
                <td>{factor.drop_priority}</td>
                <td>
                  {factor.sourced ? (
                    `${factor.weight_count} cited`
                  ) : (
                    <span className="shell-empty">none — not scored in Mode B</span>
                  )}
                </td>
                <td>
                  {factor.adapters.length === 0 ? (
                    <span className="shell-empty">no adapter</span>
                  ) : (
                    factor.adapters.map((adapter) => (
                      <div key={adapter.name}>
                        <span className="shell-mono">{adapter.name}</span> · tier{" "}
                        {adapter.tier} · {adapter.licence}
                      </div>
                    ))
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
