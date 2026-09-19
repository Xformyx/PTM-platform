import assert from "node:assert/strict";
import test from "node:test";
import { conditionMinutes, orderedConditions, viewportBounds, scatterCount, binBounds, scatterAxes } from "../src/lib/scatterOverview.ts";
import type { ScatterCondition } from "../src/lib/scatterOverview.ts";

test("condition order uses time units and deterministic labels", () => {
  const conditions = ["180min", "1h", "5min", "30sec", "10ms", "unknown"].map(condition => ({ condition } as ScatterCondition));
  assert.deepEqual(orderedConditions(conditions).map(c => c.condition), ["10ms", "30sec", "5min", "1h", "180min", "unknown"]);
  assert.equal(conditionMinutes("2days"), 2880);
});
test("zoom changes the real viewport; zero and nonzero density bounds are explicit", () => {
  const full = viewportBounds([-2, 2, -4, 4], 1), zoom = viewportBounds([-2, 2, -4, 4], 2);
  assert.equal(zoom[1] - zoom[0], (full[1] - full[0]) / 2);
  assert.deepEqual(binBounds({ ix: 0, iy: 63 }, [-2, 2, -4, 4], 64), [-2, -1.9375, 3.875, 4]);
  assert.ok(viewportBounds([0, 0, 0, 0], 1).every(Number.isFinite));
});
test("display aggregation preserves row totals and U has its own label", () => {
  assert.equal(scatterCount({ mode: "density", bins: [{ count: 2000 }, { count: 17 }] } as ScatterCondition), 2017);
  assert.equal(scatterCount({ mode: "points", points: [{ x: 0, y: 0 }, { x: 0, y: 0 }] } as ScatterCondition), 2);
  assert.equal(scatterAxes.unadjusted.short, "U log₂FC");
});
