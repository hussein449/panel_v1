import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// One file out, everything inlined.
//
// The report has to open from a `file://` URL with no server running — that is the
// done-when for step 4.3, and it is not an arbitrary bar. A corridor can be assessed
// offline with no network and no API key; a report that then needed a web server to be
// read would have put the network back into the one product that does without it.
//
// So there is no asset directory, no code splitting and no external stylesheet. The
// build emits a single `report.html` into the Python package, which ships it and
// injects a run into it.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: "../src/roadrisk/report/static",
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 100_000_000,
    target: "es2020",
    rollupOptions: {
      output: { inlineDynamicImports: true },
    },
  },
});
