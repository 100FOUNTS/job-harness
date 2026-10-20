// SEEK Quick Apply with Playwright (no LLM, no extension). One job per run.
// Usage: node apply_seek.js <slug> <jobId> <cv.pdf> <letter.pdf> <dry|submit> <profileDir> <key>
// Uses a dedicated Chrome profile where the candidate logged in once (`job apply <slug> login seek`).
// Every question goes through scripts/answer.py: approved answers first, safe rules otherwise; improvised
// answers are recorded in pending_questions.json. Prints one JSON line with the outcome.
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const path = require("path");

const [, , slug, jobId, cv, letter, mode, profileDir, key] = process.argv;
const ROOT = path.resolve(__dirname, "..");
const out = { key, outcome: "failed", note: "", answered: [], unanswered: [] };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const human = () => sleep(600 + Math.random() * 900);

function answer(question, type, options) {
  const r = execFileSync("python3", [path.join(ROOT, "scripts/answer.py"), slug, "--question", question, "--type", type,
    "--options", options.join("|"), "--job", key], { cwd: ROOT, encoding: "utf8" });
  return JSON.parse(r.trim().split("\n").pop());
}

async function clickContinue(page) {
  const btn = page.getByRole("button", { name: /^continue$/i }).first();
  await btn.waitFor({ timeout: 15000 });
  await human(); await btn.click();
  await page.waitForLoadState("domcontentloaded"); await sleep(2500);
}

async function answerQuestions(page) {
  for (const sel of await page.locator("select").all()) {
    const label = (await sel.evaluate((e) => (e.labels && e.labels[0] ? e.labels[0].innerText : e.getAttribute("aria-label") || e.name))).trim();
    const opts = (await sel.locator("option").allInnerTexts()).map((t) => t.trim()).filter(Boolean);
    const r = answer(label, "select", opts);
    if (r.answer) { await sel.selectOption({ label: r.answer }); out.answered.push({ q: label, a: r.answer, src: r.source }); }
    else out.unanswered.push(label);
    await human();
  }
  for (const fs of await page.locator("fieldset").all()) {
    const legend = ((await fs.locator("legend").first().innerText().catch(() => "")) || "").trim();
    const inputs = await fs.locator("input[type=radio], input[type=checkbox]").all();
    if (!legend || !inputs.length) continue;
    const labels = [];
    for (const i of inputs) labels.push((await i.evaluate((e) => (e.labels && e.labels[0] ? e.labels[0].innerText : e.value))).trim());
    const type = (await inputs[0].getAttribute("type")) === "checkbox" ? "checkbox" : "radio";
    const r = answer(legend, type, labels);
    const idx = labels.findIndex((l) => l === r.answer);
    if (idx >= 0) { await inputs[idx].check({ force: true }); out.answered.push({ q: legend, a: r.answer, src: r.source }); }
    else out.unanswered.push(legend);
    await human();
  }
  for (const t of await page.locator("textarea, input[type=text], input[type=number]").all()) {
    if (!(await t.isVisible()) || (await t.inputValue())) continue;
    const label = (await t.evaluate((e) => (e.labels && e.labels[0] ? e.labels[0].innerText : e.getAttribute("aria-label") || e.name || ""))).trim();
    if (!label) continue;
    const r = answer(label, (await t.evaluate((e) => e.tagName)) === "TEXTAREA" ? "text" : "number", []);
    if (r.answer) { await t.fill(String(r.answer)); out.answered.push({ q: label, a: r.answer, src: r.source }); }
    else out.unanswered.push(label);
    await human();
  }
}

(async () => {
  const ctx = await chromium.launchPersistentContext(profileDir, { channel: "chrome", headless: false,
    viewport: { width: 1280, height: 900 } });
  const page = ctx.pages()[0] || (await ctx.newPage());
  try {
    await page.goto(`https://www.seek.com.au/job/${jobId}/apply`, { waitUntil: "domcontentloaded" });
    await sleep(3500);
    if (/login|sign-in|oauth/i.test(page.url())) { out.outcome = "needs-login"; out.note = `Log in once: job apply ${slug} login seek`; return; }
    if (!/\/apply/.test(page.url())) { out.outcome = "manual-review"; out.note = "Not a SEEK Quick Apply job (external application): " + page.url(); return; }

    // 1. Documents: first file input = resumé, second = cover letter. Keep the master CV as the profile default.
    const files = page.locator("input[type=file]");
    await files.nth(0).setInputFiles(cv); await sleep(4000);
    const def = page.getByLabel(/make this my default resum/i);
    if (await def.count() && (await def.first().isChecked())) await def.first().uncheck({ force: true });
    await files.nth(1).setInputFiles(letter); await sleep(4000);
    await clickContinue(page);

    // 2. Employer questions (if any) → 3. SEEK profile step → 4. Review
    for (let step = 0; step < 4; step++) {
      if (/role-requirements|questions/.test(page.url())) await answerQuestions(page);
      if (/review/.test(page.url())) break;
      await clickContinue(page);
    }
    if (!/review/.test(page.url())) { out.outcome = "manual-review"; out.note = "Did not reach the review step: " + page.url(); return; }
    if (mode !== "submit") { out.outcome = "dry-run"; out.note = "Filled up to review, not submitted"; return; }
    const submit = page.getByRole("button", { name: /submit application/i }).first();
    await human(); await submit.click();
    await page.waitForLoadState("domcontentloaded"); await sleep(5000);
    const ok = /success|application (has been )?(sent|submitted)|you('ve| have) applied/i.test(await page.locator("body").innerText());
    out.outcome = ok ? "submitted" : "manual-review";
    out.note = ok ? "SEEK confirmation shown" : "Clicked submit but no confirmation found: check SEEK 'Applied jobs'";
  } catch (e) {
    out.outcome = "failed"; out.note = String(e.message || e).slice(0, 300);
  } finally {
    console.log(JSON.stringify(out));
    await ctx.close();
  }
})();
