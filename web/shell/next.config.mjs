// Next reports anonymous usage to Vercel on every build unless told not to. Nothing else
// in this repository phones home — the report makes no external request at all, and
// every source an adapter touches is declared with its licence — so a build tool doing
// it quietly is out of keeping. The scripts in `package.json` set this too; this line is
// for anyone who runs `next` directly.
process.env.NEXT_TELEMETRY_DISABLED = "1";

/**
 * The shell's build.
 *
 * **`transpilePackages`** is here because `roadrisk-report` is TypeScript source, not a
 * build. That is deliberate: step 5.3a's library target exists for hosts that are *not*
 * React and have to be handed a compiled bundle, and this host is React, so it imports
 * the components themselves. Next compiles them with the same toolchain as the rest of
 * the app, which is also what lets the report's stylesheet be imported here at all.
 *
 * **There is one React**, hoisted to `web/node_modules` by the workspace. That matters
 * more than it looks: two copies of React in one document is a broken hooks dispatcher
 * rather than a large download, and a linked package is the usual way to end up with
 * two. It is also why this app is on Next 14 — the shell takes the report's React
 * version, not the other way round, because the report is the product and a shell step
 * has no business changing the bundle the Python package ships.
 *
 * **No ESLint.** `npm run lint` is `tsc --noEmit`, and the build should not fail on a
 * linter that is not installed.
 *
 * @type {import('next').NextConfig}
 */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["roadrisk-report"],
  eslint: { ignoreDuringBuilds: true },
  poweredByHeader: false,
};

export default nextConfig;
