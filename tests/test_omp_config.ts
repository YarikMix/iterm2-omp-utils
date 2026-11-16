import { describe, expect, test } from "bun:test";
import { transform } from "../runtime/omp_config.ts";

type Snapshot = { exists: boolean; value: unknown };
const absent = { exists: false, value: null };
const present = (value: unknown) => ({ exists: true, value });
const read = (source: string, kind: string, key: string) => transform({ source, kind, key, operation: "read" }).value;
const patch = (source: string, kind: string, key: string, value: Snapshot, expected: Snapshot) =>
  transform({ source, kind, key, operation: "patch", value, expected }).source!;

describe("owned native addresses", () => {
  test("nested settings and literal action IDs preserve neighbours and comments", () => {
    const source = "# user heading\nterminal:\n  programStatus: false # chosen\n  other: 'unchanged' # neighbour\nmodel: keep\n";
    const after = patch(source, "setting", "terminal.programStatus", present(true), present(false));
    expect(after).toBe(source.replace("programStatus: false", "programStatus: true"));
    expect(read(after, "setting", "terminal.programStatus")).toEqual(present(true));
    const binding = "# shortcuts\napp.session.resume: null\napp.history.search: Ctrl+R # foreign\n";
    const changed = patch(binding, "binding", "app.session.resume", present("Alt+R"), present(null));
    expect(changed).toContain('app.session.resume: "Alt+R"');
    expect(changed).toContain("app.history.search: Ctrl+R # foreign");
    expect(read(changed, "binding", "app.session.resume")).toEqual(present("Alt+R"));
    expect(read(changed, "binding", "app.session")).toEqual(absent);
  });

  test("native notification enums and explicit null are distinct from absence", () => {
    for (const key of ["completion.notify", "error.notify"]) {
      const after = patch("# kept\n", "setting", key, present("on"), absent);
      expect(read(after, "setting", key)).toEqual(present("on"));
      const restored = patch(after, "setting", key, absent, present("on"));
      expect(read(restored, "setting", key)).toEqual(absent);
      expect(restored).toContain("# kept");
      expect(() => patch("", "setting", key, present(true), absent)).toThrow();
    }
    expect(read("terminal:\n  programStatus: null\n", "setting", "terminal.programStatus")).toEqual(present(null));
    expect(read("", "setting", "terminal.programStatus")).toEqual(absent);
  });

  test("inverse refuses changed value and ambiguous parents", () => {
    expect(() => patch("terminal: {programStatus: null}\n", "setting", "terminal.programStatus", absent, present(true))).toThrow();
    for (const source of ["terminal: null\n", "terminal: []\n", "terminal: x\n", "terminal.programStatus: false\n"]) {
      expect(() => patch(source, "setting", "terminal.programStatus", present(true), absent)).toThrow();
    }
  });

  test("malformed documents never become empty settings", () => {
    for (const source of ["[]", "null", "terminal: [", "a: 1\na: 2\n", "---\na: 1\n---\nb: 2\n", "a: !custom value\n"]) {
      expect(() => read(source, "setting", "terminal.programStatus")).toThrow();
    }
  });

  test("unrelated YAML syntax survives but aliases on the owned path are refused", () => {
    const source = "# keep\nforeign: &base {x: 2}\ncopy: *base\nterminal: {programStatus: false, other: 9}\n";
    const after = patch(source, "setting", "terminal.programStatus", present(true), present(false));
    expect(after).toBe(source.replace("programStatus: false", "programStatus: true"));
    for (const text of ["terminal: &base {programStatus: false}\ncopy: *base\n", "base: &base {programStatus: false}\nterminal: *base\n", "terminal: {<<: {programStatus: false}}\n"]) {
      expect(() => patch(text, "setting", "terminal.programStatus", present(true), present(false))).toThrow();
    }
  });

  test("binding arrays, empty disables and removals round trip", () => {
    const source = "# keep\napp.session.resume: [Alt+R, F6]\napp.history.search: Ctrl+R\n";
    const after = patch(source, "binding", "app.session.resume", present([]), present(["Alt+R", "F6"]));
    expect(read(after, "binding", "app.session.resume")).toEqual(present([]));
    const restored = patch(after, "binding", "app.session.resume", present(["Alt+R", "F6"]), present([]));
    expect(read(restored, "binding", "app.session.resume")).toEqual(present(["Alt+R", "F6"]));
    const removed = patch(source, "binding", "app.session.resume", absent, present(["Alt+R", "F6"]));
    expect(read(removed, "binding", "app.session.resume")).toEqual(absent);
    expect(removed).toContain("# keep");
    expect(removed).toContain("app.history.search: Ctrl+R");
  });

  test("bounded requests and unsupported addresses are refused", () => {
    expect(() => read("x".repeat(1048577), "setting", "terminal.programStatus")).toThrow();
    expect(() => read("", "setting", "model")).toThrow();
    expect(() => read("", "binding", "__proto__")).toThrow();
    expect(() => transform({ source: "", kind: "setting", key: "terminal.programStatus", operation: "exec" })).toThrow();
  });
});
