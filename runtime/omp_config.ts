/** Pure, bounded YAML address transforms. No omp imports, filesystem or network. */
import { Document, isAlias, isMap, isScalar, isSeq, parseAllDocuments, parseDocument, visit } from "../vendor/yaml/dist/index.js";

const LIMIT = 1024 * 1024;
type Value = { exists: boolean; value: unknown };
type Request = { op: "read" | "patch"; raw: string; pointer: string[]; expected?: Value; next?: Value };
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
function jsonValue(value: unknown, seen = new Set<object>(), depth = 0, count = { n: 0, bytes: 0 }): void {
  if (depth > 64 || ++count.n > 100000) fail();
  if (value === null || typeof value === "string" || typeof value === "boolean" || typeof value === "number") {
    if (typeof value === "number" && (!Number.isFinite(value) || Number.isInteger(value) && !Number.isSafeInteger(value))) fail();
    count.bytes += Buffer.byteLength(JSON.stringify(value));
    if (count.bytes > 2 * LIMIT) fail();
    return;
  }
  if (typeof value !== "object" || seen.has(value)) fail();
  seen.add(value);
  count.bytes += 2;
  // Only own string-keyed entries are traversed after the object guard.
  const record = value as Record<string, unknown>;
  let first = true;
  for (const key of Object.keys(record)) {
    if (!first) count.bytes++;
    first = false;
    if (!Array.isArray(value)) count.bytes += Buffer.byteLength(JSON.stringify(key)) + 1;
    if (count.bytes > 2 * LIMIT) fail();
    jsonValue(record[key], seen, depth + 1, count);
  }
  seen.delete(value);
}
function wrapped(value: Value | undefined): asserts value is Value {
  if (!value || typeof value.exists !== "boolean" || Object.keys(value).sort().join() !== "exists,value" || (!value.exists && value.value !== null)) fail();
  jsonValue(value.value);
}
function validateRequest(request: unknown): asserts request is Request {
  if (!request || typeof request !== "object" || Array.isArray(request) ||
      !("op" in request) || request.op !== "read" && request.op !== "patch" ||
      !("raw" in request) || typeof request.raw !== "string" ||
      !("pointer" in request) || !Array.isArray(request.pointer)) fail();
  const fields = request.op === "read" ? ["op", "raw", "pointer"] : ["op", "raw", "pointer", "expected", "next"];
  if (Object.keys(request).length !== fields.length || fields.some(field => !Object.hasOwn(request, field)) ||
      request.pointer.length > 64 || request.op === "patch" && request.pointer.length === 0 ||
      request.pointer.some(part => typeof part !== "string" || !part || part.length > 256 ||
        /[\x00-\x1f]/.test(part) || ["__proto__", "prototype", "constructor"].includes(part))) fail();
}
function document(source: string) {
  if (typeof source !== "string" || Buffer.byteLength(source) > LIMIT) fail();
  const options = { keepSourceTokens: true, uniqueKeys: true, strict: true, prettyErrors: false, logLevel: "silent", version: "1.2" };
  // parseDocument suppresses MULTIPLE_DOCS in silent mode. Count the complete
  // stream independently before any read or mutation can discard later docs.
  const documents = parseAllDocuments(source, options);
  if (documents.length > 1 || documents.some(doc => doc.errors.length || doc.warnings.length)) fail();
  // The empty-stream result carries stream errors; parseDocument is used only
  // after the count check to preserve a comment-only document's metadata.
  if ("errors" in documents && documents.errors.length || "warnings" in documents && documents.warnings.length) fail();
  const doc = documents[0] ?? parseDocument(source, options);
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

export function transform(request: unknown): { value?: Value; raw?: string } {
  validateRequest(request);
  const { raw, pointer } = request;
  const doc = document(raw);
  const current = address(doc, pointer);
  if (request.op === "read") return { value: current.value };
  wrapped(request.expected); wrapped(request.next);
  if (!same(current.value, request.expected)) fail();
  if (same(current.value, request.next)) return { raw };
  let result: string;
  const span = current.node?.range;
  const inline = isScalar(current.node) && current.node.type !== "BLOCK_LITERAL" && current.node.type !== "BLOCK_FOLDED" ||
    isSeq(current.node) && current.node.flow;
  if (request.next.exists && span && span[1] > span[0] && inline && !/[\r\n]/.test(raw.slice(span[0], span[1]))) {
    // Only genuinely inline spans may be spliced. Block/multiline scalars use
    // Document mutation to retain their newline boundaries and header comments.
    const [start, end] = span;
    result = raw.slice(0, start) + JSON.stringify(request.next.value) + raw.slice(end);
  } else {
    if (request.next.exists) doc.setIn(pointer, request.next.value);
    else {
      // A heading may be attached to the first key rather than the document.
      // Preserve comments from a removed pair instead of deleting user prose.
      const parent = doc.getIn(pointer.slice(0, -1), true);
      const pair = isMap(parent) ? parent.items.find(item => isScalar(item.key) && item.key.value === pointer[pointer.length - 1]) : undefined;
      const comments = [pair?.key?.commentBefore, pair?.key?.comment, pair?.value?.commentBefore, pair?.value?.comment].filter(value => typeof value === "string");
      doc.deleteIn(pointer);
      if (comments.length) doc.commentBefore = [doc.commentBefore, ...comments].filter(value => typeof value === "string").join("\n");
    }
    result = doc.toString({ lineWidth: 0 });
  }
  if (Buffer.byteLength(result) > LIMIT) fail();
  const actual = address(document(result), pointer).value;
  if (!same(actual, request.next)) fail();
  return { raw: result };
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
    const response = JSON.stringify(transform(request));
    if (Buffer.byteLength(response) > 2 * LIMIT) fail();
    process.stdout.write(response + "\n");
  } catch {
    process.stdout.write('{"error":"native_config_conflict"}\n');
    process.exitCode = 1;
  } finally { clearTimeout(timer); }
}
