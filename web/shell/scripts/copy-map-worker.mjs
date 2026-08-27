/**
 * Put MapLibre's worker where the browser can actually fetch it.
 *
 * **Why this exists.** MapLibre works out its worker's URL at runtime, from
 * `import.meta.url`:
 *
 *     let url = import.meta.url;                       // inside a bundle, the chunk's URL
 *     return new URL("./maplibre-gl-worker.mjs", url); // → /_next/static/chunks/…
 *
 * Inside a webpack bundle that resolves to a chunk URL, so it asks for a worker beside
 * the chunk, there is no such file, Next answers with its 404 **page**, and the browser
 * refuses it: *"Failed to load module script: the server responded with a non-JavaScript
 * MIME type of text/html"*. The map then draws a canvas, mounts its controls, and never
 * fires `load` — a perfectly convincing empty map. It cost an afternoon to notice, which
 * is why `RunMapCanvas` now listens for the map's own error event and says so on screen.
 *
 * **Why a copy rather than a bundler trick.** The worker imports
 * `./maplibre-gl-shared.mjs` relatively, so it has to land in a directory beside its
 * sibling. Emitting it as a webpack asset moves it away from that sibling and breaks the
 * import instead. Two files copied into `public/` is the honest fix: the browser fetches
 * exactly what the package shipped, and `setWorkerUrl` in `RunMapCanvas` points at it.
 *
 * The copy is a build artefact of `node_modules` and is git-ignored. It runs from
 * `predev` and `prebuild`, so it cannot be forgotten.
 */

import { createRequire } from "node:module";
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/** Must match `WORKER_URL` in `components/RunMapCanvas.tsx`. A test asserts it does. */
const DESTINATION = "public/maplibre";

const FILES = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];

const here = dirname(fileURLToPath(import.meta.url));
const shell = dirname(here);

// Resolved through `package.json` rather than through the package itself: MapLibre's
// export map offers only an `import` condition for `.`, so asking `require.resolve` for
// it is `ERR_PACKAGE_PATH_NOT_EXPORTED`. `./package.json` is exported, and it is beside
// the directory we want.
const dist = join(
  dirname(createRequire(import.meta.url).resolve("maplibre-gl/package.json")),
  "dist",
);
const into = join(shell, DESTINATION);

mkdirSync(into, { recursive: true });
for (const file of FILES) {
  copyFileSync(join(dist, file), join(into, file));
}

console.log(`Copied ${FILES.length} MapLibre worker files into ${DESTINATION}/`);
