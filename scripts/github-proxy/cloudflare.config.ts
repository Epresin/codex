import { defineConfig } from "cf/config";
import * as entrypoint from "./src/index.ts" with { type: "cf-worker" };

export default defineConfig({
  worker: {
    name: "github-edge",
    compatibilityDate: "2026-10-10",
    entrypoint,
    domains: ["gh.mccts.cn"],
    workersDev: false,
    previewUrls: false,
  },
});
