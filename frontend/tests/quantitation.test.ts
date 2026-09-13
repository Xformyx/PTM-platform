import { test } from "node:test";
import assert from "node:assert/strict";
import { axisValue, supportedChange, observedGrid, sampledExtremumIndex } from "../src/lib/quantitation.ts";
const base = { gene: "G", position: "S1", feature_id: "F1", condition: "5min" };
test("sampled extrema withhold flat, tied and incomplete grids", () => {
  for (const values of [[0, 0, 0], [1, 1, 1], [1, null, 1], [1, -1, 0]]) {
    assert.equal(sampledExtremumIndex(values), null);
  }
  assert.equal(sampledExtremumIndex([0, -2, 1]), 1);
});
test("canonical null and independent U survive legacy values", () => {
  const row = { ...base, ptm_unadjusted_log2fc: 1, ptm_protein_adjusted_log2fc: null, ptm_relative_log2fc: 9, protein_log2fc: null };
  assert.equal(axisValue(row, "relative"), null);
  assert.equal(axisValue(row, "protein"), null);
  assert.equal(axisValue(row, "unadjusted"), 1);
});
test("effect and q must belong to the same condition and axis", () => {
  const rows = [{ ...base, ptm_unadjusted_log2fc: 2, ptm_unadjusted_q_value: .5 },
    { ...base, condition: "40min", ptm_unadjusted_log2fc: .1, ptm_unadjusted_q_value: .001 }];
  assert.equal(supportedChange(rows, "unadjusted"), false);
  assert.equal(supportedChange([{ ...rows[0], ptm_unadjusted_q_value: .001 }], "unadjusted"), true);
  assert.equal(supportedChange([{ ...rows[0], ptm_protein_adjusted_q_value: .001 }], "unadjusted"), false);
});
test("distinct forms, absent observations and true zero are order invariant", () => {
  const rows = [{ ...base, ptm_unadjusted_log2fc: 1 },
    { ...base, feature_id: "F2", condition: "40min", ptm_unadjusted_log2fc: -1 },
    { ...base, condition: "180min", ptm_unadjusted_log2fc: 0 }];
  for (const input of [rows, [...rows].reverse()]) {
    assert.deepEqual(observedGrid(input, base, ["5min", "40min", "180min"], "unadjusted"), [1, null, 0]);
    assert.deepEqual(observedGrid(input, { ...base, feature_id: "F2" }, ["5min", "40min", "180min"], "unadjusted"), [null, -1, null]);
  }
});
