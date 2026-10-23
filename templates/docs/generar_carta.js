// One-page cover letter (Australian formal letter layout) from a JSON file.
// Usage: node generar_carta.js <input.json> <output.docx>
const fs = require("fs");
const { Document, Packer, Paragraph, TextRun, AlignmentType } = require("docx");

const [, , input = "cover_letter.json", output = "Cover_Letter.docx"] = process.argv;
const cl = JSON.parse(fs.readFileSync(input, "utf8"));

const FONT = "Arial";
const SIZE = 21; // 10.5 pt

const line = (text, opts = {}) => new Paragraph({
  spacing: { after: 0 },
  children: [new TextRun({ text, size: SIZE, font: FONT, ...opts })],
});
const gap = () => new Paragraph({ spacing: { after: 0 }, children: [new TextRun({ text: "", size: SIZE })] });
const para = (text) => new Paragraph({
  alignment: AlignmentType.JUSTIFIED,
  spacing: { after: 160, line: 264 },
  children: [new TextRun({ text, size: SIZE, font: FONT })],
});

const order = ["purpose", "why_company", "technical", "australia", "closing"];
const body = order.map((k) => cl.paragraphs[k]).filter(Boolean);

const children = [
  line(cl.sender[0], { bold: true, size: 26, color: "1F4E3D" }),
  ...cl.sender.slice(1).map((s) => line(s)),
  gap(),
  line(cl.date),
  gap(),
  ...cl.recipient.filter((r) => r && !r.includes("optional")).map((r) => line(r)),
  gap(),
  line(cl.salutation),
  gap(),
  line(cl.re, { bold: true }),
  gap(),
  ...body.flatMap((t) => [para(t), gap()]),
  line(cl.sign_off),
  gap(),
  gap(),
  line(cl.name),
  gap(),
  line(cl.enclosure),
];

const doc = new Document({
  creator: cl.name || "",
  title: `${cl.name || "Candidate"} – Cover Letter`,
  styles: { default: { document: { run: { font: FONT, size: SIZE } } } },
  sections: [{ properties: { page: { margin: { top: 1134, bottom: 1134, left: 1247, right: 1247 } } }, children }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(output, buf);
  console.log(`OK: ${output}`);
});
