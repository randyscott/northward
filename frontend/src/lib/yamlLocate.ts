// Find the YAML text a server issue points at. Issue locations look like `accounts[joint_brokerage].owner` or
// `levers.ss_claim_ages.alex`: dotted keys, and list items named by their id (or name, or index).
import { isMap, isPair, isScalar, isSeq, LineCounter, parseDocument, type Node } from "yaml";

export interface Span {
  startLine: number; // 1-based, as Monaco counts
  startColumn: number;
  endLine: number;
  endColumn: number;
}

export function parseLocation(location: string): string[] {
  const segments: string[] = [];
  for (const match of location.matchAll(/\[([^\]]*)\]|([^.[\]]+)/g)) segments.push((match[1] ?? match[2])!);
  return segments;
}

function scalarValue(node: unknown): unknown {
  return isScalar(node) ? node.value : undefined;
}

/** The span of the deepest node of `location` that exists in `text` (the whole first line if none does). */
export function locate(text: string, location: string): Span {
  const lineCounter = new LineCounter();
  const doc = parseDocument(text, { lineCounter });
  let node: unknown = doc.contents;
  let range: [number, number] | null = null;
  for (const segment of parseLocation(location.replace(/\s*\(.*?\)\s*/g, ""))) {
    if (isMap(node)) {
      const pair = node.items.find((item) => isPair(item) && String(scalarValue(item.key)) === segment);
      if (!pair) break;
      const key = pair.key as Node | null;
      if (key?.range) range = [key.range[0], (pair.value as Node | null)?.range?.[1] ?? key.range[1]];
      node = pair.value;
    } else if (isSeq(node)) {
      const items = node.items as Node[];
      let item = items.find(
        (candidate) =>
          isMap(candidate) && [candidate.get("id"), candidate.get("name")].some((v) => String(v) === segment),
      );
      if (!item && /^\d+$/.test(segment)) item = items[Number(segment)];
      if (!item) break;
      if (item.range) range = [item.range[0], item.range[1]];
      node = item;
    } else {
      break;
    }
  }
  if (!range)
    return { startLine: 1, startColumn: 1, endLine: 1, endColumn: Math.max(2, (text.split("\n")[0] ?? "").length + 1) };
  const start = lineCounter.linePos(range[0]);
  // Mark the first line of the node (a whole multi-line item underlined reads as noise).
  const lineEnd = text.indexOf("\n", range[0]);
  const end = lineCounter.linePos(Math.min(range[1], lineEnd === -1 ? text.length : lineEnd));
  return {
    startLine: start.line,
    startColumn: start.col,
    endLine: end.line,
    endColumn: Math.max(end.col, start.col + 1),
  };
}
