// ATS-safe CV (one column, no tables, no header/footer) from a JSON file.
// Usage: node generar_cv.js <input.json> <output.docx>
const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, AlignmentType, BorderStyle,
  LevelFormat,
} = require("docx");

const [, , input = "cv.json", output = "Resume.docx"] = process.argv;
const cv = JSON.parse(fs.readFileSync(input, "utf8"));

const FONT = "Arial";
const SIZE = 20; // 10 pt
const LINE = 276; // 1.15 line spacing

// Pages ignores "space before" on paragraphs: gaps are fixed-height empty paragraphs instead.
const spacer = (pt) => new Paragraph({
  spacing: { before: 0, after: 0, line: pt * 20, lineRule: "exact" },
  children: [new TextRun({ text: "", size: 2 })],
});

const heading = (text) => [spacer(10), new Paragraph({
  keepNext: true,
  spacing: { before: 340, after: 140 },
  border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: "1F4E3D", space: 2 } },
  children: [new TextRun({ text: text.toUpperCase(), bold: true, size: 23, color: "1F4E3D", font: FONT })],
})];

const body = (text, opts = {}) => new Paragraph({
  spacing: { after: 80, line: LINE },
  ...opts,
  children: [new TextRun({ text, size: SIZE, font: FONT })],
});

const bullet = (text) => new Paragraph({
  numbering: { reference: "bullets", level: 0 },
  spacing: { after: 60, line: LINE },
  children: [new TextRun({ text, size: SIZE, font: FONT })],
});

// "Label: text" with the label in bold (skills, one-line projects).
const leadBullet = ([k, v]) => new Paragraph({
  numbering: { reference: "bullets", level: 0 },
  spacing: { after: 70, line: LINE },
  children: [
    new TextRun({ text: `${k}: `, bold: true, size: SIZE, font: FONT }),
    new TextRun({ text: v, size: SIZE, font: FONT }),
  ],
});

// Role in bold; employer and dates on the next line (no tab stops: reads the same in Word, Pages and ATS).
const entry = (e, i) => {
  const out = [
    ...(i > 0 ? [spacer(7)] : []),
    new Paragraph({
      spacing: { before: 240, after: 20 },
      keepNext: true,
      children: [new TextRun({ text: e.role, bold: true, size: SIZE, font: FONT })],
    }),
    new Paragraph({
      spacing: { after: 100 },
      keepNext: true,
      children: [new TextRun({ text: e.dates ? `${e.org}  |  ${e.dates}` : e.org, italics: true, size: SIZE, font: FONT })],
    }),
  ];
  e.bullets.forEach((b) => out.push(bullet(b)));
  return out;
};

const children = [
  new Paragraph({
    alignment: AlignmentType.LEFT,
    spacing: { after: 0 },
    children: [new TextRun({ text: cv.name, bold: true, size: 40, color: "1F4E3D", font: FONT })],
  }),
  new Paragraph({
    alignment: AlignmentType.LEFT,
    spacing: { before: 40, after: 80 },
    children: [new TextRun({ text: cv.title, size: 24, font: FONT, color: "44564D" })],
  }),
  body(cv.contact),

  ...heading("Professional Summary"),
  body(cv.summary, { alignment: AlignmentType.JUSTIFIED }),

  ...heading("Key Skills"),
  ...cv.skills.map(leadBullet),

  ...heading("Work Experience"),
  ...cv.experience.flatMap(entry),
];

if (cv.entrepreneurship?.length) children.push(...heading("Entrepreneurship"), ...cv.entrepreneurship.flatMap(entry));
const projectsTitle = cv.projects_heading || "Projects";   // e.g. "Data and AI Projects (Self-Directed Study, 2026)"
if (typeof cv.projects === "string") children.push(...heading(projectsTitle), body(cv.projects, { alignment: AlignmentType.JUSTIFIED }));
else if (cv.projects?.length) children.push(...heading(projectsTitle), ...cv.projects.flatMap((p, i) => (typeof p === "string" ? [bullet(p)] : Array.isArray(p) ? [leadBullet(p)] : entry(p, i))));
if (cv.other_employment?.length) children.push(...heading("Other Employment"), ...cv.other_employment.flatMap(entry));

children.push(...heading("Education and Qualifications"));
cv.education.forEach(([q, inst, year], i) => children.push(...(i > 0 ? [spacer(5)] : []), new Paragraph({
  spacing: { after: 40, line: LINE },
  children: [
    new TextRun({ text: q, bold: true, size: SIZE, font: FONT }),
    new TextRun({ text: `${inst}  |  ${year}`, italics: true, size: SIZE, font: FONT, break: 1 }),
  ],
})));

if (cv.publications?.length) children.push(...heading("Publications"), ...cv.publications.map(bullet));
const extra = (label, text) => new Paragraph({
  spacing: { after: 60, line: LINE },
  children: [
    new TextRun({ text: `${label}: `, bold: true, size: SIZE, font: FONT }),
    new TextRun({ text, size: SIZE, font: FONT }),
  ],
});
children.push(...heading("Additional Information"));
children.push(new Paragraph({
  spacing: { after: 60, line: LINE },
  children: [
    ...(cv.certificates?.length ? [
      new TextRun({ text: "Certificates: ", bold: true, size: SIZE, font: FONT }),
      new TextRun({ text: `${cv.certificates.join(", ")}     `, size: SIZE, font: FONT }),
    ] : []),
    new TextRun({ text: "Languages: ", bold: true, size: SIZE, font: FONT }),
    new TextRun({ text: cv.languages, size: SIZE, font: FONT }),
    ...(cv.referees ? [                                   // empty: no referees line at all
      new TextRun({ text: "Referees: ", bold: true, size: SIZE, font: FONT, break: 1 }),
      new TextRun({ text: cv.referees, size: SIZE, font: FONT }),
    ] : []),
  ],
}));

const doc = new Document({
  creator: cv.name || "",
  title: `${cv.name} – Resume`,
  styles: { default: { document: { run: { font: FONT, size: SIZE } } } },
  numbering: {
    config: [{
      reference: "bullets",
      levels: [{
        level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 360, hanging: 240 } } },
      }],
    }],
  },
  sections: [{
    properties: { page: { margin: { top: 800, bottom: 760, left: 1134, right: 1134 } } },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync(output, buf);
  console.log(`OK: ${output}`);
});
