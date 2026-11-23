// Text helpers shared by generar_cv.js (docx) and generar_pdf.js (pdf), so both render a CV line the same way.

const MONTHS = {
  january: "Jan", february: "Feb", march: "Mar", april: "Apr", june: "Jun", july: "Jul",
  august: "Aug", september: "Sep", sept: "Sep", october: "Oct", november: "Nov", december: "Dec",
};

// Date ranges with an ASCII hyphen (some ATS imports, Workday, drop a date joined by an en dash) and full month
// names cut to three letters ("Expected December 2026" -> "Expected Dec 2026"), so every date in the CV has one
// format. Bare years ("2019") are left alone: no month is invented.
const cleanDates = (s) => String(s ?? "")
  .replace(/\s*[‐-―−]\s*/g, " - ")
  .replace(/\b(january|february|march|april|june|july|august|september|sept|october|november|december)\b/gi,
    (m) => MONTHS[m.toLowerCase()]);

// "Org, City  |  Mon YYYY - Mon YYYY  |  Part-time": the dates and the optional employment type (`type`) follow the org.
const orgLine = (e) => [e.org, e.dates ? cleanDates(e.dates) : "", e.type ? String(e.type).trim() : ""]
  .filter((x) => x !== undefined && x !== null && x !== "").join("  |  ");

module.exports = { cleanDates, orgLine };
