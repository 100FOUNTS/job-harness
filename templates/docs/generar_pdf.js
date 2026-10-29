// PDF directly from the CV / cover letter JSON (no Pages, no LibreOffice: runs unattended from launchd).
// Helvetica is a standard PDF font without ligatures, so ATS text extraction stays clean.
// Usage: node generar_pdf.js cv|letter <input.json> <output.pdf>
const fs = require("fs");
const PDFDocument = require("pdfkit");

const [, , kind, input, output] = process.argv;
const d = JSON.parse(fs.readFileSync(input, "utf8"));
const GREEN = "#1F4E3D", GREY = "#44564D";
const M = 54; // ~1.9 cm margins
const doc = new PDFDocument({ size: "A4", margins: { top: 40, bottom: 40, left: M, right: M },
  info: { Title: `${d.name || "Candidate"} – ${kind === "cv" ? "Resume" : "Cover Letter"}`, Author: d.name || "" } });
doc.pipe(fs.createWriteStream(output));
const W = doc.page.width - 2 * M;
const BODY = 9.3;

const ensure = (h) => { if (doc.y + h > doc.page.height - doc.page.margins.bottom) doc.addPage(); };
const para = (t, o = {}) => doc.font(o.bold ? "Helvetica-Bold" : o.italic ? "Helvetica-Oblique" : "Helvetica")
  .fontSize(o.size || BODY).fillColor(o.color || "black").text(t, M, doc.y, { width: W, lineGap: 1.5, align: o.align || "left" });

function heading(t) {
  ensure(60);
  doc.moveDown(0.7);
  doc.font("Helvetica-Bold").fontSize(11.2).fillColor(GREEN).text(t.toUpperCase(), M, doc.y, { width: W });
  const y = doc.y + 1.5;
  doc.moveTo(M, y).lineTo(M + W, y).lineWidth(0.7).strokeColor(GREEN).stroke();
  doc.y = y + 5;
}

function bullet(t, boldLead) {
  const h = doc.font("Helvetica").fontSize(BODY).heightOfString(t, { width: W - 14, lineGap: 1.5 });
  ensure(h + 2);
  const y = doc.y;
  doc.font("Helvetica").fontSize(BODY).fillColor("black").text("•", M + 2, y);
  if (boldLead) {
    doc.font("Helvetica-Bold").text(`${boldLead}: `, M + 14, y, { width: W - 14, lineGap: 1.5, continued: true })
      .font("Helvetica").text(t);
  } else {
    doc.text(t, M + 14, y, { width: W - 14, lineGap: 1.5 });
  }
  doc.y += 2.2;
}

function entry(e, i) {
  ensure(50);
  if (i > 0) doc.moveDown(0.55);
  para(e.role, { bold: true });
  para(e.dates ? `${e.org}  |  ${e.dates}` : e.org, { italic: true, color: GREY });
  doc.y += 2;
  (e.bullets || []).forEach((b) => bullet(b));
}

if (kind === "cv") {
  doc.font("Helvetica-Bold").fontSize(20).fillColor(GREEN).text(d.name, M, doc.y, { width: W });
  para(d.title, { size: 11.5, color: GREY });
  doc.y += 2;
  para(d.contact, { size: 9.2 });
  heading("Professional Summary"); para(d.summary);
  heading("Key Skills"); d.skills.forEach(([k, v]) => bullet(v, k));
  heading("Work Experience"); d.experience.forEach(entry);
  if (d.entrepreneurship?.length) { heading("Entrepreneurship"); d.entrepreneurship.forEach(entry); }
  if (d.projects?.length) { heading("Projects"); d.projects.forEach((p, i) => (typeof p === "string" ? bullet(p) : Array.isArray(p) ? bullet(p[1], p[0]) : entry(p, i))); }
  if (d.other_employment?.length) { heading("Other Employment"); d.other_employment.forEach(entry); }
  heading("Education and Qualifications");
  d.education.forEach(([q, inst, year], i) => { ensure(30); if (i) doc.y += 4; para(q, { bold: true }); para(`${inst}  |  ${year}`, { italic: true, color: GREY }); });
  if (d.publications?.length) { heading("Publications"); d.publications.forEach((p) => bullet(p)); }
  heading("Additional Information");
  if (d.certificates?.length) para(`Certificates: ${d.certificates.join(", ")}`);
  para(`Languages: ${d.languages}`);
  para(`Referees: ${d.referees}`);
} else {
  const order = ["purpose", "why_company", "technical", "australia", "closing"];
  doc.font("Helvetica-Bold").fontSize(13).fillColor(GREEN).text(d.sender[0], M, doc.y, { width: W });
  d.sender.slice(1).forEach((s) => para(s, { size: 9.6 }));
  doc.moveDown(1); para(d.date);
  doc.moveDown(1); d.recipient.filter((r) => r && !r.includes("{{") && !r.includes("optional")).forEach((r) => para(r));
  doc.moveDown(1); para(d.salutation);
  doc.moveDown(1); para(d.re, { bold: true });
  doc.moveDown(0.8);
  order.map((k) => d.paragraphs[k]).filter(Boolean).forEach((t) => { para(t, { size: 10, align: "justify" }); doc.moveDown(0.75); });
  para(d.sign_off, { size: 10 }); doc.moveDown(2); para(d.name, { size: 10 });
  doc.moveDown(1); para(d.enclosure, { size: 9.6 });
}
doc.end();
