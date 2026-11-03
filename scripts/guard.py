"""Posting guard: an ad is third-party text that Claude later reads next to the candidate's data. Clean it before it
is stored, and flag what looks aimed at an AI instead of a reader. Idea from ai-job-search (tools/posting_guard.py).

  job guard <file.html|file.txt>      → JSON {flags, removed} for a saved ad (the daily run applies it on fetch)

clean(html) removes, before the tags are stripped:
- elements hidden from a reader (style display:none / visibility:hidden / font-size:0 / opacity:0, the `hidden`
  attribute, aria-hidden="true"), comments, script/style/template;
- invisible characters: zero-width, bidi controls, soft hyphen, BOM, Unicode tag characters (an invisible alphabet).
Instruction-shaped lines in the visible text are kept (an ad may legitimately say "prompt engineering") and flagged.
The removal is the defence; the flags are for the person. Nothing here ever blocks the daily run.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

HIDDEN_STYLE = r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d]*[1-9])|opacity\s*:\s*0(?![.\d]*[1-9])"
HIDDEN_TAG = re.compile(rf'<(\w+)\b[^>]*(?:style="[^"]*(?:{HIDDEN_STYLE})[^"]*"|\shidden(?:[\s>=])|aria-hidden="true")[^>]*>.*?</\1\s*>',
                        re.I | re.S)
INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩­﻿]|[\U000e0000-\U000e007f]")
AIMED_AT_AI = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|prompts)|disregard (the|all|previous) instructions|"
    r"(if|when) you are an? (ai|llm|language model|assistant|bot)|as an ai\b|you are (chatgpt|claude|an ai)|"
    r"system prompt|(ai|llm|chatgpt|claude),? (please )?(include|mention|write|respond|reply|add)|"
    r"include the (word|phrase) ['\"]", re.I)


def clean(raw: str) -> tuple[str, dict[str, int]]:
    """(plain text a reader sees, counts of what was removed or flagged)."""
    flags = {"hidden_blocks": 0, "hidden_aimed_at_ai": 0, "invisible_chars": 0, "aimed_at_ai": 0}
    s = re.sub(r"<!--.*?-->|<(script|style|template|noscript)\b.*?</\1\s*>", " ", raw or "", flags=re.I | re.S)
    while (m := HIDDEN_TAG.search(s)):
        flags["hidden_blocks"] += 1
        hidden = html.unescape(re.sub(r"<[^>]+>", " ", m.group(0)))
        flags["hidden_aimed_at_ai"] += bool(AIMED_AT_AI.search(hidden))
        s = s[:m.start()] + " " + s[m.end():]
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    flags["invisible_chars"] = len(INVISIBLE.findall(s))
    s = INVISIBLE.sub("", s)
    text = " ".join(s.split())
    flags["aimed_at_ai"] = len(AIMED_AT_AI.findall(text))
    return text, flags


def suspicious(flags: dict[str, int]) -> bool:
    """What the person should hear about: text aimed at an AI (visible or hidden), or a hidden invisible alphabet."""
    return bool(flags.get("aimed_at_ai") or flags.get("hidden_aimed_at_ai") or flags.get("invisible_chars", 0) > 3)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    a = ap.parse_args()
    _, flags = clean(Path(a.file).read_text(errors="ignore", encoding="utf-8"))
    print(json.dumps({"flags": flags, "suspicious": suspicious(flags)}, indent=2))


if __name__ == "__main__":
    main()
