// The document editor: Monaco on a model named like the document (profiles/<p>/<address>.yaml), so monaco-yaml
// applies the right schema. Server issues are shown as markers on the lines they point at.
import { useEffect, useRef } from "react";

import type { Span } from "../lib/yamlLocate";
import { editorTheme, monaco } from "./monaco";

export interface Marker extends Span {
  message: string;
}

export default function YamlEditor({
  path,
  value,
  onChange,
  markers = [],
  readOnly = false,
  onSave,
}: {
  path: string;
  value: string;
  onChange?: (text: string) => void;
  markers?: Marker[];
  readOnly?: boolean;
  onSave?: () => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const editor = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const handlers = useRef({ onChange, onSave });
  handlers.current = { onChange, onSave };

  useEffect(() => {
    const uri = monaco.Uri.parse(`file:///${path}`);
    const model = monaco.editor.getModel(uri) ?? monaco.editor.createModel(value, "yaml", uri);
    model.setValue(value);
    const instance = monaco.editor.create(host.current!, {
      model,
      readOnly,
      automaticLayout: true,
      minimap: { enabled: false },
      fontSize: 13,
      tabSize: 2,
      insertSpaces: true,
      scrollBeyondLastLine: false,
      renderWhitespace: "boundary",
      theme: editorTheme(),
      quickSuggestions: { other: true, comments: false, strings: true },
    });
    editor.current = instance;
    const changes = model.onDidChangeContent(() => handlers.current.onChange?.(model.getValue()));
    instance.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => handlers.current.onSave?.());
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const retheme = () => monaco.editor.setTheme(editorTheme());
    media?.addEventListener?.("change", retheme);
    return () => {
      media?.removeEventListener?.("change", retheme);
      changes.dispose();
      instance.dispose();
      model.dispose();
      editor.current = null;
    };
  }, [path, readOnly]); // one editor per document; later `value` changes arrive through the effect below

  useEffect(() => {
    const model = editor.current?.getModel();
    if (model && model.getValue() !== value) model.setValue(value);
  }, [value]);

  useEffect(() => {
    const model = editor.current?.getModel();
    if (!model) return;
    monaco.editor.setModelMarkers(
      model,
      "northward",
      markers.map((m) => ({
        ...m,
        endLineNumber: m.endLine,
        endColumn: m.endColumn,
        startLineNumber: m.startLine,
        startColumn: m.startColumn,
        severity: monaco.MarkerSeverity.Error,
        source: "northward",
      })),
    );
  }, [markers]);

  return <div className="editor" ref={host} data-testid="yaml-editor" />;
}
