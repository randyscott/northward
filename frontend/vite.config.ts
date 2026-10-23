import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// monaco-yaml's worker helper still imports Monaco by its old file path (monaco-editor/esm/vs/...), which Monaco
// 0.57's package exports no longer allow; point that path at the files directly.
const monacoEsm = fileURLToPath(new URL("./node_modules/monaco-editor/esm/vs/", import.meta.url));
// ...and its worker manager creates workers through an API Monaco 0.57 replaced; use our updated copy.
const workerManager = fileURLToPath(new URL("./src/components/monacoWorkerManager.ts", import.meta.url));

// In development the API runs separately (`make serve`); the dev server forwards /api to it.
const api = process.env.NORTHWARD_API ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^monaco-editor\/esm\/vs\/(.*)$/, replacement: `${monacoEsm}$1` },
      { find: /^monaco-worker-manager$/, replacement: workerManager },
    ],
  },
  server: { port: 5173, proxy: { "/api": api } },
  build: { chunkSizeWarningLimit: 5000 }, // Plotly and Monaco are large; they load on the pages that use them
  test: {
    environment: "jsdom",
    globals: true,
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["src/test/setup.ts"],
  },
});
