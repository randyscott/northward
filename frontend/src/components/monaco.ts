// Monaco plus monaco-yaml for schema-driven completion, hover, and validation. Loaded only by the pages that edit
// documents. In Monaco 0.57 the editor's contributions (suggestions, hovers, folding, ...) come only with
// the package root; its language grammars load lazily, on first use.
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import { configureMonacoYaml, type MonacoYaml } from "monaco-yaml";

import YamlWorker from "./yaml.worker.ts?worker";

self.MonacoEnvironment = {
  getWorker(_moduleId: string, label: string) {
    return label === "yaml" ? new YamlWorker() : new EditorWorker();
  },
};

let yaml: MonacoYaml | null = null;

/** Attach the document kinds' JSON Schemas: profile documents by file name, scenarios by folder. */
export function setSchemas(schemas: Record<string, object>): void {
  const entries = Object.entries(schemas).map(([kind, schema]) => ({
    uri: `inmemory://northward/schemas/${kind}.json`,
    fileMatch: kind === "scenario" ? ["**/profiles/*/scenarios/*.yaml"] : [`**/profiles/*/${kind}.yaml`],
    schema,
  }));
  const options = { enableSchemaRequest: false, hover: true, completion: true, validate: true, schemas: entries };
  if (yaml) yaml.update(options);
  else yaml = configureMonacoYaml(monaco, options);
}

export function editorTheme(): string {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "vs-dark" : "vs";
}

export { monaco };
