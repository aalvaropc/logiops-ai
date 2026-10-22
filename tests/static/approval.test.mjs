import { test } from "node:test";
import assert from "node:assert/strict";
import { moduleUrl } from "./helpers.mjs";

const { recordedNote } = await import(moduleUrl("app/approval.js"));

test("nothing is said when the approval is recorded under the name that was typed", () => {
  assert.equal(recordedNote("Maria", { approved_by: "Maria" }), null);
});

test("the person is told whose name is on record when the server recorded another", () => {
  const note = recordedNote("Maria", { approved_by: "demo-operator" });
  assert.match(note, /“demo-operator”/);
  assert.match(note, /not “Maria”/);
});

test("a response without an approver says nothing", () => {
  assert.equal(recordedNote("Maria", {}), null);
  assert.equal(recordedNote("Maria", undefined), null);
});
