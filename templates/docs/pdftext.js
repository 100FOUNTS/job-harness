// Read a PDF without Poppler: pdf.js (pure JavaScript) is already installed with the document generators.
// Usage: node pdftext.js <file.pdf> [--pages | --lines | --text]
//   --pages  page count
//   --lines  JSON [{height, lines: [{top, bottom, text}]}] per page, top-down like `pdftotext -bbox`
//   --text   plain text in reading order, pages separated by a form feed
const fs = require("fs");

const ASCENT = 0.72, DESCENT = 0.21; // Helvetica metrics: what pdftotext -bbox reports around the baseline

async function load(file) {
  const log = console.log;
  console.log = () => {}; // pdf.js prints canvas polyfill warnings on stdout at import; text extraction needs no canvas
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
  console.log = log;
  const data = new Uint8Array(fs.readFileSync(file));
  return pdfjs.getDocument({ data, verbosity: 0, useSystemFonts: true, isEvalSupported: false }).promise;
}

function toLines(items, height) {
  const words = items.filter((i) => i.str.trim()).map((i) => {
    const size = Math.hypot(i.transform[2], i.transform[3]) || i.height;
    return { x: i.transform[4], base: height - i.transform[5], size, w: i.width, s: i.str };
  });
  words.sort((a, b) => a.base - b.base || a.x - b.x);
  const rows = [];
  for (const w of words) {
    const row = rows.find((r) => Math.abs(r.base - w.base) < 0.4 * Math.min(r.size, w.size));
    row ? row.words.push(w) : rows.push({ base: w.base, size: w.size, words: [w] });
  }
  return rows.sort((a, b) => a.base - b.base).map((r) => {
    r.words.sort((a, b) => a.x - b.x);
    let text = "", end = null;
    for (const w of r.words) {
      const s = w.s.replace(/\s+/g, " ");
      if (end !== null && w.x - end > 0.1 * w.size && !text.endsWith(" ") && !s.startsWith(" ")) text += " ";
      text += s;
      end = w.x + w.w;
    }
    const size = Math.max(...r.words.map((w) => w.size));
    return { top: +(r.base - ASCENT * size).toFixed(2), bottom: +(r.base + DESCENT * size).toFixed(2),
             text: text.replace(/\s+/g, " ").trim(), size };
  });
}

async function pages(pdf) {
  const out = [];
  for (let n = 1; n <= pdf.numPages; n++) {
    const page = await pdf.getPage(n);
    const height = page.view[3] - page.view[1];
    const { items } = await page.getTextContent();
    out.push({ height, lines: toLines(items, height) });
  }
  return out;
}

function plain(ps) {
  return ps.map((p) => p.lines.map((l, i, all) => {
    const gap = i ? l.top - all[i - 1].bottom : 0;
    return (gap > 0.7 * l.size ? "\n" : "") + l.text;
  }).join("\n")).join("\n\f");
}

(async () => {
  const [, , file, mode = "--text"] = process.argv;
  if (!file || !fs.existsSync(file)) { console.error(`pdftext: no such file: ${file || "(none)"}`); process.exit(2); }
  const pdf = await load(file);
  if (mode === "--pages") return console.log(pdf.numPages);
  const ps = await pages(pdf);
  if (mode === "--lines") console.log(JSON.stringify(ps.map((p) => ({ height: p.height, lines: p.lines.map(({ top, bottom, text }) => ({ top, bottom, text })) }))));
  else process.stdout.write(plain(ps) + "\n");
})().catch((e) => { console.error(`pdftext: ${e.message || e}`); process.exit(1); });
