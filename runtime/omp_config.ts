/** Pure, bounded YAML address transforms. No omp imports, filesystem or network. */
import { Document, isAlias, isMap, isScalar, isSeq, parseDocument, visit } from "../vendor/yaml/dist/index.js";

const LIMIT = 1024 * 1024;
const SETTINGS: Record<string, true> = { "terminal.programStatus": true, "completion.notify": true, "error.notify": true };
const ACTION = /^(?:app|tui)\.[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*$/;
type Value = { exists: boolean; value: unknown };
type Request = { source: string; kind: string; key: string; operation: string; value?: Value; expected?: Value };
const absent = (): Value => ({ exists: false, value: null });

function fail(): never { throw new Error("Unsupported or conflicting native configuration"); }
function same(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null) return false;
  if (Array.isArray(a) || Array.isArray(b)) return Array.isArray(a) && Array.isArray(b) && a.length === b.length && a.every((v, i) => same(v, b[i]));
  if (typeof a !== "object") return false;
  const x = a as Record<string, unknown>, y = b as Record<string, unknown>;
  return Object.keys(x).length === Object.keys(y).length && Object.keys(x).every(k => Object.hasOwn(y, k) && same(x[k], y[k]));
}
function jsonValue(value: unknown, seen = new Set<object>(), depth = 0, count = { n: 0 }): void {
  if (depth > 64 || ++count.n > 100000) fail();
  if (value === null || typeof value === "string" || typeof value === "boolean") return;
  if (typeof value === "number") { if (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value))) fail(); return; }
  if (typeof value !== "object" || seen.has(value)) fail();
  seen.add(value);
  for (const child of Object.values(value)) jsonValue(child, seen, depth + 1, count);
  seen.delete(value);
}
function wrapped(value: Value | undefined): asserts value is Value {
  if (!value || typeof value.exists !== "boolean" || Object.keys(value).sort().join() !== "exists,value" || (!value.exists && value.value !== null)) fail();
  jsonValue(value.value);
}
function nativeValue(kind: string, key: string, value: unknown): void {
  // Null is a real stored value and must remain restorable, not become absence.
  if (value === null) return;
  if (kind === "setting") {
    if (key === "terminal.programStatus" ? typeof value !== "boolean" : value !== "on" && value !== "off") fail();
  } else {
    const chords = Array.isArray(value) ? value : [value];
    if (chords.length > 64 || chords.some(v => typeof v !== "string" || !v.trim() || v.length > 100 || /[\r\n\x00-\x1f]/.test(v))) fail();
  }
}
function document(source: string) {
  if (typeof source !== "string" || Buffer.byteLength(source) > LIMIT) fail();
  const doc = parseDocument(source, { keepSourceTokens: true, uniqueKeys: true, strict: true, prettyErrors: false, logLevel: "silent", version: "1.2" });
  if (doc.errors.length || doc.warnings.length || (doc.contents !== null && !isMap(doc.contents))) fail();
  // Empty/comment-only source is absence; explicit null is malformed storage.
  if (doc.contents === null && source.replace(/#[^\r\n]*/g, "").trim()) fail();
  visit(doc, {
    Node(_key, node) { if (node.tag) fail(); },
    Pair(_key, pair) { if (!isScalar(pair.key) || typeof pair.key.value !== "string") fail(); },
  });
  const root = doc.contents === null ? {} : doc.toJS({ maxAliasCount: 50 });
  jsonValue(root);
  return doc;
}
function address(doc: Document, path: string[]) {
  let node = doc.contents;
  if (node === null) return { value: absent(), node: undefined };
  for (let i = 0; i < path.length; i++) {
    // Never mutate an anchor (which could silently change foreign aliases), an
    // inherited merge, or a scalar parent. Unrelated anchors remain untouched.
    if (!isMap(node) || node.anchor || node.has("<<")) fail();
    if (!node.has(path[i])) return { value: absent(), node: undefined };
    node = node.get(path[i], true);
    if (isAlias(node) || node?.anchor) fail();
  }
  return { value: { exists: true, value: node == null ? null : node.toJS(doc, { maxAliasCount: 50 }) }, node };
}

export function transform(request: Request): { value?: Value; source?: string; bindings?: Record<string, unknown> } {
  if (!request || !["setting", "binding"].includes(request.kind) || typeof request.key !== "string" ||
      (request.kind === "setting" ? !Object.hasOwn(SETTINGS, request.key) : !ACTION.test(request.key)) ||
      !["read", "patch", "bindings"].includes(request.operation)) fail();
  const { source, kind, key } = request;
  const doc = document(source);
  if (kind === "setting" && doc.has(key)) fail(); // literal dotted settings are not native nested storage
  if (request.operation === "bindings") {
    if (kind !== "binding") fail();
    const bindings = doc.contents === null ? {} : doc.toJS({ maxAliasCount: 50 });
    for (const [action, value] of Object.entries(bindings)) {
      if (!ACTION.test(action)) fail(); // legacy unqualified actions require explicit native migration
      nativeValue("binding", action, value);
    }
    return { bindings };
  }
  const path = kind === "setting" ? key.split(".") : [key];
  const current = address(doc, path);
  if (current.value.exists) nativeValue(kind, key, current.value.value);
  if (request.operation === "read") return { value: current.value };
  wrapped(request.expected); wrapped(request.value);
  if (!same(current.value, request.expected)) fail();
  if (request.value.exists) nativeValue(kind, key, request.value.value);
  if (same(current.value, request.value)) return { source, value: current.value };
  let result: string;
  if (request.value.exists && current.node?.range && current.node.range[1] > current.node.range[0] && (isScalar(current.node) || isSeq(current.node) && current.node.flow)) {
    // Replace only the value span: all foreign whitespace, quoting and comments
    // remain byte-identical, including flow maps and literal dotted action IDs.
    const [start, end] = current.node.range;
    result = source.slice(0, start) + JSON.stringify(request.value.value) + source.slice(end);
  } else {
    if (request.value.exists) doc.setIn(path, request.value.value);
    else {
      // A heading may be attached to the first key rather than the document.
      // Preserve comments from a removed pair instead of deleting user prose.
      const parent = doc.getIn(path.slice(0, -1), true);
      const pair = isMap(parent) ? parent.items.find(item => isScalar(item.key) && item.key.value === path[path.length - 1]) : undefined;
      const comments = [pair?.key?.commentBefore, pair?.key?.comment, pair?.value?.commentBefore, pair?.value?.comment].filter(value => typeof value === "string");
      doc.deleteIn(path);
      if (comments.length) doc.commentBefore = [doc.commentBefore, ...comments].filter(value => typeof value === "string").join("\n");
    }
    result = doc.toString({ lineWidth: 0 });
  }
  if (Buffer.byteLength(result) > LIMIT) fail();
  const actual = address(document(result), path).value;
  if (!same(actual, request.value)) fail();
  return { source: result, value: actual };
}

if (import.meta.main) {
  // Parent also enforces a five-second wall-clock deadline. Never emit parser
  // diagnostics: those may contain credentials or other foreign source text.
  const timer = setTimeout(() => process.exit(1), 4500);
  try {
    const chunks: Uint8Array[] = [];
    let length = 0;
    for await (const chunk of Bun.stdin.stream()) {
      length += chunk.length;
      if (length > 2 * LIMIT) fail();
      chunks.push(chunk);
    }
    const request = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    process.stdout.write(JSON.stringify(transform(request)) + "\n");
  } catch {
    process.stdout.write('{"error":"native_config_conflict"}\n');
    process.exitCode = 1;
  } finally { clearTimeout(timer); }
}
