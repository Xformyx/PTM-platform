// Actual production component/CSS through Vite; HTTP uses real reader fixtures.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { writeFileSync } from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const options = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, i, all) => i % 2 ? pairs : [...pairs, [value.replace(/^--/, ""), all[i + 1]]], []));
const fixtureDir = options["fixture-dir"], output = options.output;
if (!fixtureDir || !output) throw new Error("--fixture-dir and --output are required");
await fs.mkdir(output, { recursive: true });
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch({ headless: true, ...(options.browser ? { executablePath: options.browser } : {}) });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
const errors = [], requests = [], scenarios = [];
function recordScenario(name) {
  scenarios.push(name);
  const progress = { timestamp: new Date().toISOString(), completed_scenarios: scenarios.length, last_scenario: name };
  writeFileSync(path.join(output, "progress.json"), JSON.stringify(progress, null, 2));
  console.log(JSON.stringify({ event: "scenario_passed", ...progress }));
}
page.on("pageerror", error => errors.push(String(error)));
page.on("request", request => { if (request.url().includes("/api/")) requests.push({ method: request.method(), url: request.url() }); });
let source = "small", fail = false, heldAxis = false, heldOrder = false, pending = [];
const fixture = async (name, axis) => JSON.parse(await fs.readFile(path.join(fixtureDir, `${name}-${axis}.json`), "utf8"));
await page.route("**/api/orders/**", async route => {
  const url = new URL(route.request().url());
  assert.equal(route.request().method(), "GET", "Scatter must never enqueue work");
  if (url.pathname.includes("/files/")) {
    return route.fulfill({ body: await fs.readFile(path.join(fixtureDir, "small", "ptm_vector_data_normalized_phospho.tsv")),
      contentType: "text/tab-separated-values", headers: { "Content-Disposition": "attachment; filename=original.tsv" } });
  }
  assert.ok(url.pathname.endsWith("/vector-scatter-data"), `Unexpected API: ${url.pathname}`);
  const axis = url.searchParams.get("axis") || "adjusted";
  const order = url.pathname.split("/")[3];
  const data = await fixture(order === "2" ? "other" : source, axis);
  if ((heldAxis && axis === "unadjusted") || (heldOrder && order === "1")) { pending.push({ route, data }); return; }
  if (fail) return route.fulfill({ status: 503, json: { detail: "synthetic source read failure" } });
  return route.fulfill({ json: data });
});
const waitCounts = async n => page.waitForFunction(n => document.querySelector('[data-testid="scatter-counts"]')?.textContent?.includes(`원본 ${n.toLocaleString()}행`), n);
const axis = name => page.getByRole("button", { name, exact: true });
const canvas = () => page.locator("canvas").first();
async function pointerAt(x, y) {
  await page.waitForFunction(() => {
    const c = document.querySelector("canvas");
    return c && Math.abs(c.width - c.getBoundingClientRect().width * devicePixelRatio) <= 1;
  });
  const box = await canvas().boundingBox();
  const v = JSON.parse(await canvas().getAttribute("data-viewport"));
  // An axis change can keep the same screen coordinate; force pointer leave
  // and re-entry so the new Canvas receives a real pointer event.
  await page.mouse.move(1, 1);
  await page.mouse.move(box.x + 48 + (x - v[0]) / (v[1] - v[0]) * (box.width - 60),
    box.y + 15 + (v[3] - y) / (v[3] - v[2]) * 225);
}
try {
  await page.goto(`${options.url || "http://127.0.0.1:5173"}/tests/scatter.browser.html`);
  await waitCounts(150);
  assert.equal(await page.getByTestId("scatter-condition").count(), 6);
  await page.waitForFunction(() => [...document.querySelectorAll("canvas")].every(c => {
    const pixels = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
    let n = 0; for (let i = 3; i < pixels.length; i += 4) n += pixels[i] > 0; return n > 500;
  }));
  recordScenario("legacy TSV / six condition cards / nonempty Canvas");
  await pointerAt(0, 0);
  await page.getByTestId("scatter-hover").first().filter({ hasText: "precursor p0" }).waitFor();
  await page.screenshot({ path: path.join(output, "scatter-desktop-hover.png"), fullPage: true });
  recordScenario("precursor/raw label hover including real zero");
  const before = JSON.parse(await canvas().getAttribute("data-viewport"));
  await page.getByRole("button", { name: "확대", exact: true }).click();
  const after = JSON.parse(await canvas().getAttribute("data-viewport"));
  assert.ok(after[1] - after[0] < before[1] - before[0]);
  await page.getByRole("button", { name: "축소", exact: true }).click();
  recordScenario("real viewport zoom in/out");
  await axis("Independent PTM (U)").click();
  await page.locator('canvas[aria-label*="U log₂FC"]').first().waitFor();
  await pointerAt(0, 2);
  await page.getByTestId("scatter-hover").first().filter({ hasText: "U log₂FC=2" }).waitFor();
  await axis("Paired occupancy").click();
  await page.locator('canvas[aria-label*="Occupancy Δlogit"]').first().waitFor();
  assert.ok((await page.getByTestId("scatter-counts").innerText()).includes("표시 가능 78행"));
  recordScenario("independent U / quality-gated paired occupancy");
  heldAxis = true;
  await axis("Independent PTM (U)").click();
  await page.waitForTimeout(150); assert.equal(pending.length, 1);
  await axis("Protein-adjusted PTM (A)").click();
  await page.locator('canvas[aria-label*="A log₂FC"]').first().waitFor();
  heldAxis = false;
  for (const item of pending.splice(0)) await item.route.fulfill({ json: item.data }).catch(() => {});
  await page.waitForTimeout(150);
  assert.equal(await page.locator('canvas[aria-label*="U log₂FC"]').count(), 0);
  recordScenario("late previous axis response discarded");
  await page.getByRole("button", { name: "시험 주문 변경" }).click(); await waitCounts(12);
  heldOrder = true;
  await page.getByRole("button", { name: "시험 주문 변경" }).click();
  await page.waitForTimeout(150); assert.equal(pending.length, 1);
  await page.getByRole("button", { name: "시험 주문 변경" }).click(); await waitCounts(12);
  heldOrder = false;
  for (const item of pending.splice(0)) await item.route.fulfill({ json: item.data }).catch(() => {});
  await page.waitForTimeout(150); await waitCounts(12);
  recordScenario("late previous order response discarded");
  await page.getByRole("button", { name: "시험 주문 변경" }).click(); await waitCounts(150);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(200);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({ path: path.join(output, "scatter-mobile.png"), fullPage: true });
  recordScenario("390px mobile without horizontal overflow");
  const downloadPromise = page.waitForEvent("download");
  await axis("원본 TSV").click();
  const download = await downloadPromise;
  await download.saveAs(path.join(output, "downloaded-source.tsv"));
  assert.deepEqual(await fs.readFile(path.join(output, "downloaded-source.tsv")), await fs.readFile(path.join(fixtureDir, "small", "ptm_vector_data_normalized_phospho.tsv")));
  recordScenario("authorized source download without write requests");
  fail = true;
  await axis("Independent PTM (U)").click();
  await page.getByRole("alert").waitFor(); assert.equal(await page.locator("canvas").count(), 0);
  await page.screenshot({ path: path.join(output, "scatter-error.png"), fullPage: true });
  fail = false;
  await axis("다시 시도").click(); await waitCounts(150);
  recordScenario("read error / no blank canvas / retry");
  source = "large";
  await page.setViewportSize({ width: 1440, height: 1100 });
  await axis("Protein-adjusted PTM (A)").click(); await waitCounts(120000);
  assert.equal(await page.getByText(/전체 밀도 집계/).count(), 6);
  const large = await fixture("large", "adjusted");
  assert.equal(large.conditions.reduce((s, c) => s + c.bins.reduce((n, b) => n + b.count, 0), 0), 120000);
  const bin = large.conditions[0].bins[0], b = large.bounds, n = large.bin_resolution;
  await pointerAt(b[0] + (bin.ix + .5) * (b[1] - b[0]) / n, b[2] + (bin.iy + .5) * (b[3] - b[2]) / n);
  await page.getByTestId("scatter-hover").first().filter({ hasText: "구간 관측" }).waitFor();
  await page.screenshot({ path: path.join(output, "scatter-density.png"), fullPage: true });
  recordScenario("120,000 whole-row bins / density range hover");
  source = "constant";
  await page.reload(); await waitCounts(2001);
  await pointerAt(0, 0);
  await page.getByTestId("scatter-hover").first().filter({ hasText: "구간 관측 2001행" }).waitFor();
  recordScenario("constant zero density / all 2,001 source rows accessible on hover");
  source = "empty";
  await page.reload(); await waitCounts(0);
  await page.getByText("원본 TSV에 관측행이 없습니다.", { exact: true }).waitFor();
  assert.equal(await page.locator("canvas").count(), 0);
  source = "noeligible";
  await page.reload(); await waitCounts(1);
  await page.getByText("선택한 두 축에 적격한 관측이 없습니다. 제외 사유와 다른 축을 확인하세요.", { exact: true }).waitFor();
  assert.equal(await page.locator("canvas").count(), 0);
  recordScenario("empty source distinguished from axis-ineligible source without blank Canvas");
  assert.ok(requests.every(r => r.method === "GET")); assert.deepEqual(errors, []);
  recordScenario("zero browser errors / zero worker or write requests");
  const result = { synthetic_only: true, full_login_order_e2e: false, browser: browser.version(), scenarios, errors,
    scenario_count: scenarios.length, request_count: requests.length, write_requests: requests.filter(r => r.method !== "GET").length };
  await fs.writeFile(path.join(output, "browser-result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} catch (error) {
  await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true });
  await fs.writeFile(path.join(output, "failure.json"), JSON.stringify({ error: String(error), scenarios, errors,
    body: await page.locator("body").innerText() }, null, 2));
  throw error;
} finally { await browser.close(); }
