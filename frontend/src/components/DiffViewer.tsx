// Side-by-side diff of two revisions (read-only), with unchanged stretches folded away.
import { useEffect, useRef } from "react";

import { editorTheme, monaco } from "./monaco";

export default function DiffViewer({ original, modified }: { original: string; modified: string }) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const left = monaco.editor.createModel(original, "yaml");
    const right = monaco.editor.createModel(modified, "yaml");
    const diff = monaco.editor.createDiffEditor(host.current!, {
      readOnly: true,
      originalEditable: false,
      automaticLayout: true,
      renderSideBySide: true,
      // Collapse long unchanged stretches so the changes are on screen (a click expands them).
      hideUnchangedRegions: { enabled: true, contextLineCount: 3, minimumLineCount: 5, revealLineCount: 10 },
      minimap: { enabled: false },
      scrollBeyondLastLine: false,
      fontSize: 13,
      theme: editorTheme(),
    });
    diff.setModel({ original: left, modified: right });
    return () => {
      diff.dispose();
      left.dispose();
      right.dispose();
    };
  }, [original, modified]);
  return <div className="diff" ref={host} />;
}
