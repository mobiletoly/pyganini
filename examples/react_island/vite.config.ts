import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  publicDir: "assets/public",
  build: {
    emptyOutDir: true,
    outDir: "assets/build",
    sourcemap: false,
    rollupOptions: {
      input: "assets/src/main.tsx",
      output: {
        entryFileNames: "app.js",
        assetFileNames: "app.css",
      },
    },
  },
});
