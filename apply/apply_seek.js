// SEEK Quick Apply with Playwright (no LLM, no extension). One job per run.
// Usage: node apply_seek.js <slug> <jobId> <cv.pdf> <letter.pdf> <dry|submit> <profileDir> <key> [savedCv]
// savedCv: file name of a resumé already saved on SEEK (one per area). Given → that one is selected and only the
// letter is uploaded, so the profile default never changes. Not given → the job's CV is uploaded (SEEK then makes it
// the default resumé).
// Uses a dedicated Chrome profile where the candidate logged in once (`job apply <slug> login seek`).
// Every question goes through scripts/answer.py: approved answers first, safe rules otherwise; improvised
// answers are recorded in pending_questions.json. Prints one JSON line with the outcome.
const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const path = require("path");

const [, , slug, jobId, cv, letter, mode, profileDir, key, savedCv] = process.argv;
const cvName = savedCv || path.basename(cv);
const ROOT = path.resolve(__dirname, "..");
const out = { key, outcome: "failed", note: "", answered: [], unanswered: [] };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const human = () => sleep(600 + Math.random() * 900);

function answer(question, type, options) {
  const r = execFileSync("python3", [path.join(ROOT, "scripts/answer.py"), slug, "--question", question, "--type", type,
    "--options", options.join("|"), "--job", key], { cwd: ROOT, encoding: "utf8" });
  return JSON.parse(r.trim().split("\n").pop());
}

// A stop that leaves the job for the person (manual-review) instead of guessing on their account.
class SafeStop extends Error {}

let shot = 0;
async function snap(page, label) {
  try {
    const dir = path.join(path.dirname(cv), "seek_steps");
    require("fs").mkdirSync(dir, { recursive: true });
    await page.screenshot({ path: path.join(dir, `${String(++shot).padStart(2, "0")}_${label}.png`), fullPage: true });
  } catch (e) { /* screenshots are evidence, never a reason to fail */ }
}

// The documents step has three file inputs: the profile photo (images), the resumé and the cover letter. Never pick
// one by position: by id first, then by "accepts documents, not images" and the section it sits in.
async function docInput(page, kind) {
  let inp = page.locator(`#${kind}-fileFile`);
  if (!(await inp.count())) {
    // Fallback: the inputs that take documents (not images), resumé first; checkSelected() verifies the result
    const docs = page.locator("input[type=file][accept*='pdf']:not([accept*='jpg']):not([accept*='png'])");
    if ((await docs.count()) !== 2) throw new SafeStop(`Expected 2 document file inputs, found ${await docs.count()}`);
    inp = docs.nth(kind === "resume" ? 0 : 1);
  }
  const accept = ((await inp.first().getAttribute("accept")) || "").toLowerCase();
  if (!/pdf/.test(accept) || /jpe?g|png|image\//.test(accept))
    throw new SafeStop(`The ${kind} file input does not look like a document field (accept="${accept}")`);
  return inp.first();
}

// After uploading, the file must be the one selected for its section, and the two must be different radio groups.
async function checkSelected(page) {
  const sel = await page.$$eval("input[type=radio]:checked", (els) => els.map((e) => ({
    name: e.name, label: ((e.labels && e.labels[0] ? e.labels[0].innerText : "") || "").trim() })));
  const r = sel.find((s) => s.label === cvName), l = sel.find((s) => s.label === path.basename(letter));
  if (!r || !l || r.name === l.name)
    throw new SafeStop("Uploaded documents are not the selected resumé and cover letter: " + JSON.stringify(sel));
}

async function clickContinue(page) {
  // SEEK's label carries an invisible word joiner (U+2060): "Continue⁠"
  const btn = page.getByRole("button", { name: /^\s*continue[^a-z]*$/i }).first();
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

    // 1. Documents: resumé and cover letter into their own inputs (never the profile photo). Keep the profile default.
    await snap(page, "documents_before");
    const sameName = () => page.$$eval("input[type=radio]", (els, n) => els.filter((e) => e.labels && e.labels[0] &&
      e.labels[0].innerText.trim() === n).length, cvName);
    if (savedCv) {
      // The area's resumé is already on SEEK: select it, upload nothing, leave the default alone
      if ((await sameName()) !== 1) throw new SafeStop(`Saved resumé '${savedCv}' must appear exactly once on SEEK (found ${await sameName()})`);
      await page.getByLabel(savedCv, { exact: true }).check({ force: true }); await human();
    } else {
      const before = await sameName();
      await (await docInput(page, "resume")).setInputFiles(cv); await sleep(4000);
      // an older upload can share the file name: the new one must be there, or SEEK would send the old one
      if ((await sameName()) <= before) throw new SafeStop("The resumé upload did not show up in SEEK's list");
      out.note = "Uploaded resumé is now the SEEK default (SEEK locks that box on upload); ";
    }
    const sameLetter = () => page.$$eval("input[type=radio]", (els, n) => els.filter((e) => e.labels && e.labels[0] &&
      e.labels[0].innerText.trim() === n).length, path.basename(letter));
    const lettersBefore = await sameLetter();
    await (await docInput(page, "coverLetter")).setInputFiles(letter); await sleep(4000);
    // earlier letters share the file name: if the new one is not listed, SEEK would send another job's letter
    if ((await sameLetter()) <= lettersBefore) throw new SafeStop("The cover letter upload did not show up in SEEK's list");
    await checkSelected(page);
    await snap(page, "documents_after");
    await clickContinue(page);

    // 2. Employer questions (if any) → 3. SEEK profile step → 4. Review
    for (let step = 0; step < 4; step++) {
      if (/role-requirements|questions/.test(page.url())) await answerQuestions(page);
      if (/review/.test(page.url())) break;
      await clickContinue(page);
    }
    await snap(page, "last_step");
    if (!/review/.test(page.url())) { out.outcome = "manual-review"; out.note = "Did not reach the review step: " + page.url(); return; }
    if (mode !== "submit") { out.outcome = "dry-run"; out.note = "Filled up to review, not submitted"; return; }
    const submit = page.getByRole("button", { name: /submit application/i }).first();
    await human(); await submit.click();
    await page.waitForLoadState("domcontentloaded"); await sleep(5000);
    const ok = /success|application (has been )?(sent|submitted)|you('ve| have) applied/i.test(await page.locator("body").innerText());
    out.outcome = ok ? "submitted" : "manual-review";
    out.note = ok ? "SEEK confirmation shown" : "Clicked submit but no confirmation found: check SEEK 'Applied jobs'";
  } catch (e) {
    await snap(page, "stopped");
    out.outcome = e instanceof SafeStop ? "manual-review" : "failed"; out.note = String(e.message || e).slice(0, 300);
  } finally {
    console.log(JSON.stringify(out));
    await ctx.close();
  }
})();
