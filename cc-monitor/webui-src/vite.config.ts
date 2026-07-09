import { defineConfig } from "vite";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// Build a SINGLE self-contained index.html (JS + CSS inlined) so the Python stdlib server can
// keep serving one static document (offline, no asset routes). Output is copied to
// cc_monitor/webui_page.html (see build script) and served as a constant by webui.py.
export default defineConfig({
  plugins: [svelte(), tailwindcss(), viteSingleFile()],
  build: {
    target: "es2020",
    cssCodeSplit: false,
    assetsInlineLimit: 100000000,
    outDir: "dist",
    emptyOutDir: true,
    reportCompressedSize: false,
  },
});
