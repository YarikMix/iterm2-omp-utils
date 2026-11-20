import { describe, expect, test } from "bun:test";
import { transform } from "../runtime/omp_config.ts";

type Snapshot = { exists: boolean; value: unknown };
const absent = { exists: false, value: null };
const present = (value: unknown) => ({ exists: true, value });
const read = (raw: string, pointer: string[]) => transform({ op: "read", raw, pointer }).value;
const patch = (raw: string, pointer: string[], next: Snapshot, expected: Snapshot) =>
  transform({ op: "patch", raw, pointer, expected, next }).raw!;

describe("owned native addresses", () => {
  test("nested settings and literal action IDs preserve neighbours and comments", () => {
    const raw = "# user heading\nterminal:\n  programStatus: false # chosen\n  other: 'unchanged' # neighbour\nmodel: keep\n";
    const after = patch(raw, ["terminal", "programStatus"], present(true), present(false));
    expect(after).toBe(raw.replace("programStatus: false", "programStatus: true"));
    expect(read(after, ["terminal", "programStatus"])).toEqual(present(true));
    const binding = "# shortcuts\napp.session.resume: null\napp.history.search: Ctrl+R # foreign\n";
    const changed = patch(binding, ["app.session.resume"], present("Alt+R"), present(null));
    expect(changed).toContain('app.session.resume: "Alt+R"');
    expect(changed).toContain("app.history.search: Ctrl+R # foreign");
    expect(read(changed, ["app.session.resume"])).toEqual(present("Alt+R"));
    expect(read(changed, ["app.session"])).toEqual(absent);
  });

  test("absence and explicit null round trip through read and patch envelopes", () => {
    for (const group of ["completion", "error"]) {
      const after = patch("# kept\n", [group, "notify"], present("on"), absent);
      expect(read(after, [group, "notify"])).toEqual(present("on"));
      const restored = patch(after, [group, "notify"], absent, present("on"));
      expect(read(restored, [group, "notify"])).toEqual(absent);
      expect(restored).toContain("# kept");
    }
    expect(read("terminal:\n  programStatus: null\n", ["terminal", "programStatus"])).toEqual(present(null));
    expect(read("", ["terminal", "programStatus"])).toEqual(absent);
  });

  test("inverse refuses changed values and ambiguous parents", () => {
    expect(() => patch("terminal: {programStatus: null}\n", ["terminal", "programStatus"], absent, present(true))).toThrow();
    for (const raw of ["terminal: null\n", "terminal: []\n", "terminal: x\n"]) {
      expect(() => patch(raw, ["terminal", "programStatus"], present(true), absent)).toThrow();
    }
  });

  test("malformed documents never become empty settings", () => {
    for (const raw of ["[]", "null", "terminal: [", "a: 1\na: 2\n", "a: !custom value\n"]) {
      expect(() => read(raw, ["terminal", "programStatus"])).toThrow();
    }
  });

  test("multiple documents reject reads, forward patches and inverses", () => {
    for (const raw of [
      "foreign: keep\n---\nother: preserve\n",
      "terminal: {programStatus: true}\n---\nsecret: preserve\n",
      "---\nterminal: {programStatus: true}\n---\n",
    ]) {
      expect(() => read(raw, ["terminal", "programStatus"])).toThrow();
      expect(() => patch(raw, ["terminal", "programStatus"], present(true), absent)).toThrow();
      expect(() => patch(raw, ["terminal", "programStatus"], absent, present(true))).toThrow();
    }
  });

  test("unrelated YAML syntax survives but aliases on the owned path are refused", () => {
    const raw = "# keep\nforeign: &base {x: 2}\ncopy: *base\nterminal: {programStatus: false, other: 9}\n";
    const after = patch(raw, ["terminal", "programStatus"], present(true), present(false));
    expect(after).toBe(raw.replace("programStatus: false", "programStatus: true"));
    for (const text of ["terminal: &base {programStatus: false}\ncopy: *base\n", "base: &base {programStatus: false}\nterminal: *base\n", "terminal: {<<: {programStatus: false}}\n"]) {
      expect(() => patch(text, ["terminal", "programStatus"], present(true), present(false))).toThrow();
    }
  });

  test("binding arrays, empty disables and removals round trip", () => {
    const raw = "# keep\napp.session.resume: [Alt+R, F6]\napp.history.search: Ctrl+R\n";
    const after = patch(raw, ["app.session.resume"], present([]), present(["Alt+R", "F6"]));
    expect(read(after, ["app.session.resume"])).toEqual(present([]));
    const restored = patch(after, ["app.session.resume"], present(["Alt+R", "F6"]), present([]));
    expect(read(restored, ["app.session.resume"])).toEqual(present(["Alt+R", "F6"]));
    const removed = patch(raw, ["app.session.resume"], absent, present(["Alt+R", "F6"]));
    expect(read(removed, ["app.session.resume"])).toEqual(absent);
    expect(removed).toContain("# keep");
    expect(removed).toContain("app.history.search: Ctrl+R");
  });

  test("literal and folded binding scalars preserve following actions and header comments", () => {
    for (const style of ["|-", ">-"]) {
      for (const tail of ["app.history.search: Ctrl+R # neighbour\n", ""]) {
        const raw = `# heading\napp.session.resume: ${style} # keep header\n  Alt+R\n${tail}`;
        const after = patch(raw, ["app.session.resume"], present("F8"), present("Alt+R"));
        expect(read(after, ["app.session.resume"])).toEqual(present("F8"));
        expect(after).toContain("# keep header");
        expect(after).toContain("# heading");
        if (tail) expect(read(after, ["app.history.search"])).toEqual(present("Ctrl+R"));
        const restored = patch(after, ["app.session.resume"], present("Alt+R"), present("F8"));
        expect(read(restored, ["app.session.resume"])).toEqual(present("Alt+R"));
        expect(restored).toContain("# keep header");
        if (tail) expect(restored).toContain(tail.trim());
      }
    }
  });

  test("private protocol uses only read and patch pointer envelopes", () => {
    const raw = "app.session.resume: Alt+R\n";
    expect(transform({ op: "read", raw, pointer: [] })).toEqual({ value: present({ "app.session.resume": "Alt+R" }) });
    expect(transform({ op: "read", raw, pointer: ["app.session.resume"] })).toEqual({ value: present("Alt+R") });
    expect(transform({ op: "patch", raw, pointer: ["app.session.resume"], expected: present("Alt+R"), next: present("F8") }))
      .toEqual({ raw: 'app.session.resume: "F8"\n' });
    for (const request of [
      { op: "bindings", raw, pointer: [] },
      { operation: "read", source: raw, kind: "binding", key: "app.session.resume" },
      { op: "read", raw, pointer: [], kind: "binding" },
      { op: "patch", raw, pointer: [], expected: present({}), next: present({}) },
      { op: "patch", raw, pointer: ["app.session.resume"], next: present("F8") },
    ]) expect(() => transform(request)).toThrow();
  });

  test("bounded requests and invalid pointers are refused", () => {
    expect(() => read("x".repeat(1048577), ["terminal", "programStatus"])).toThrow();
    expect(() => read("", ["__proto__"])).toThrow();
    expect(() => read("", new Array(65).fill("part"))).toThrow();
    const aliases = `base: &base "${"x".repeat(65536)}"\n` + Array.from({ length: 40 }, (_, index) => `item${index}: *base\n`).join("");
    expect(() => read(aliases, [])).toThrow();
    expect(() => transform({ op: "exec", raw: "", pointer: [] })).toThrow();
    expect(() => transform({ op: "read", raw: "", pointer: "terminal.programStatus" })).toThrow();
  });
});
