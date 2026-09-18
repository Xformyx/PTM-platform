import test from "node:test";
import assert from "node:assert/strict";
import { LatestRequest, sharedViewRequest, finiteExtent, indexObservations, indexedTrajectory, renderedCounts, selectionLabel } from "../src/lib/vectorView.ts";

test("V08/V12/V17: precursor index retains zero, partial grids and null gaps independently of checks", () => {
  const rows = [
    {feature_id:"F1", gene:"Rps6", position:"S185", condition:"1min", ptm_protein_adjusted_log2fc: 0},
    {feature_id:"F1", gene:"Rps6", position:"S185", condition:"180min", ptm_protein_adjusted_log2fc: 2},
    {feature_id:"F2", gene:"Rps6", position:"S185", condition:"5min", ptm_protein_adjusted_log2fc: -3},
  ];
  const before = JSON.stringify(rows), index = indexObservations(rows);
  const trajectories = ["F1", "F2"].map(id => indexedTrajectory(index, id, ["1min","5min","180min"], "relative", "conventional_log2_contrast"));
  assert.deepEqual(trajectories, [[0,null,2],[null,-3,null]]);
  assert.deepEqual(renderedCounts(trajectories), {points:3,segments:0});
  assert.deepEqual(renderedCounts(trajectories.slice(1)), {points:1,segments:0});
  assert.equal(JSON.stringify(rows), before);
});

test("V20: late responses cannot overwrite the latest view and requests in flight are shared", async () => {
  const latest = new LatestRequest();
  const first = latest.begin(), second = latest.begin();
  assert.equal(latest.current(first), false);
  assert.equal(latest.current(second), true);
  let count = 0;
  const load = async () => { count++; return 42; };
  const a = sharedViewRequest("one", load), b = sharedViewRequest("one", load);
  assert.deepEqual(await Promise.all([a,b]), [42,42]);
  assert.equal(count, 1);
  await sharedViewRequest("one", load);
  assert.equal(count, 2);
});

test("large arrays preserve extrema without argument spreading", () => {
  const values = Array.from({length:1_000_000}, (_, i) => i === 999999 ? -90 : i);
  assert.deepEqual(finiteExtent(values), [-90,999998]);
});

test("selection text describes the actual union and unit", () => {
  assert.match(selectionLabel({mode:"per_condition_top_n", n:2, union_feature_count:4} as any), /Top 2.*4 precursor/);
});

test('missing kinase conditions break the SVG path without zero imputation',async()=>{
 const {observedSvgPath}=await import('../src/lib/vectorView.ts');
 assert.equal(observedSvgPath(['a','b','c','d'],{a:0,b:null,c:-2,d:1},i=>i,v=>v),'M0,0 M2,-2 L3,1');
});
