import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// Two builds out of one source tree, which is step 5.3a in one file.
//
// `npm run build` — the single file. The report has to open from a `file://` URL with no
// server running: that is the done-when for step 4.3, and it is not an arbitrary bar. A
// corridor can be assessed offline with no network and no API key, and a report that then
// needed a web server to be read would have put the network back into the one product
// that does without it. So there is no asset directory, no code splitting and no external
// stylesheet — one `report.html` into the Python package, which ships it and injects a run
// into it.
//
// `npm run build:lib` — the same report as an importable module, for a page somebody else
// owns. Step 5.3b's Next.js shell imports the component source directly, being React
// itself; this target exists for every host that is not, and because a library nobody has
// ever built is a library that does not compile.
//
// **Both are the same `<Report>`.** Neither entry point renders any part of the report, so
// the two surfaces cannot drift into drawing different things — `tests/test_report_library.py`
// asserts that rather than trusting it.
export default defineConfig(({ mode }) => {
  if (mode === "lib") {
    return {
      plugins: [react()],
      build: {
        outDir: "dist",
        emptyOutDir: true,
        cssCodeSplit: false,
        target: "es2020",
        lib: {
          entry: "src/entries/mount.tsx",
          formats: ["es"],
          fileName: () => "roadrisk-report.js",
        },
        rollupOptions: {
          // React stays external. A host page already has one, and two copies of React
          // in a document is a broken hooks dispatcher rather than a large download.
          external: ["react", "react-dom", "react/jsx-runtime", "react-dom/client"],
        },
      },
    };
  }

  return {
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
  };
});
