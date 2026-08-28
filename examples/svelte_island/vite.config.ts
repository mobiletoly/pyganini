import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [svelte()],
  publicDir: "assets/public",
  build: {
    emptyOutDir: true,
    outDir: "assets/build",
    sourcemap: false,
    rollupOptions: {
      input: "assets/src/main.ts",
      output: {
        entryFileNames: "app.js",
        assetFileNames: "app.css",
      },
    },
  },
});
