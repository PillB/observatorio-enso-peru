"""Fill the General Legal CC0 templates (pandoc HTML of the .docx originals) with the site's details.

Only fill-in fields and the template's own either/or choices are resolved. Everything else is the template text,
unchanged. Fields that still need Pablo's input stay highlighted with <mark class="pending">.
"""
import re
import sys
from pathlib import Path

DL = Path(sys.argv[1])
OUT = Path(sys.argv[2])
SITE = "https://pillb.github.io/observatorio-enso-peru/"
NAME = "Observatorio ENSO Perú"
DATE = "October 28, 2026"


def sub(s, old, new, count=1):
    n = s.count(old)
    if n != count:
        raise SystemExit(f"expected {count} of {old[:80]!r}, found {n}")
    return s.replace(old, new)


def unmark(s):
    return s.replace("<mark>", "").replace("</mark>", "")


def mark_pending(s):
    # Short bracketed fields that are still unfilled, plus the template's sample addresses.
    s = re.sub(r"\[(?:[^\[\]<>]{1,60})\]", lambda m: f'<mark class="pending">{m.group(0)}</mark>', s)
    for t in ("disputes@company.com", "email@email.com"):
        s = s.replace(t, f'<mark class="pending">{t}</mark>')
    return s


# ---------------- Privacy Policy (GDPR Enhanced) ----------------
p = (DL / "privacy-policy-gdpr-enhanced.html").read_text(encoding="utf-8")
# Template title block (drafting label) -> the policy's date line.
p = re.sub(r"\A<table>.*?</table>\n", f"<p><strong>Last Updated: {DATE}</strong></p>\n", p, count=1, flags=re.S)
p = sub(p, "Effective as of <mark>[DATE]</mark>.", f"Effective as of {DATE}.")
p = sub(p, "[<mark>Full Company Name</mark>]", NAME)
p = sub(p, "<strong>[<mark>CompanyName</mark>]</strong>", f"<strong>{NAME}</strong>")
p = sub(p, "[<mark>DESCRIPTION OF BUSINESS</mark>]",
        "free public website that publishes official El Niño and La Niña (ENSO) indicators for Peru")
p = sub(p, "[<mark>CompanyName</mark>]", NAME, count=3)
p = sub(p, "[CompanyName]", NAME, count=2)
# The Notice to European users is kept (EU scope), so its optional pointer is kept too.
p = sub(p, "<u>[<mark>NOTICE TO EUROPEAN USERS</mark></u>", "<u>NOTICE TO EUROPEAN USERS</u>")
p = sub(p, "should be understood accordingly) below.]</mark>", "should be understood accordingly) below.</mark>")
p = sub(p, "this Privacy Policy <mark>here</mark>.", 'this Privacy Policy <a href="privacy.html">here</a>.')
# Either/or choices.
p = sub(p, "[<mark>are/may be</mark>]", "may be")
p = sub(p, "<mark>[We may process Personal Information for targeted advertising purposes. You can opt-out of certain "
        "processing of personal information for targeted advertising purposes.] / [We do not process your personal "
        "information for targeted advertising purposes].</mark>",
        "We do not process your personal information for targeted advertising purposes.")
p = re.sub(r"<mark>\[We may use your Personal Information to engage in profiling.*?\] / \[(We do not use your Personal "
           r"Information to engage in profiling.*?)\]</mark>", r"\1", p, count=1, flags=re.S)
p = sub(p, "<mark>[You can opt-out of other sales of your Personal Information.]/[We do not sell your Personal "
        "Information within the meaning of State Privacy Laws.]</mark>",
        "We do not sell your Personal Information within the meaning of State Privacy Laws.")
p, n = re.subn(r"<mark><strong>\[Opt-in\.</strong>.*?\] OR \[(<strong>Consumers under 16</strong>\..*?)\]</mark>",
               r"\1", p, count=1, flags=re.S)
assert n == 1
p, n = re.subn(r"<mark>\[<strong>Limit processing of Sensitive Personal Information</strong>.*?/ \[(<strong>Sensitive "
               r"Personal Information</strong>\. We do not intentionally collect or process Sensitive Personal "
               r"Information\.)\]</mark>", r"\1", p, count=1, flags=re.S)
assert n == 1
p = mark_pending(unmark(p))

# ---------------- Terms of Use ----------------
t = (DL / "terms-of-use.html").read_text(encoding="utf-8")
t = sub(t, "202<strong><mark>[_]</mark></strong> <strong><mark>[Company]</mark></strong>", f"2026 {NAME}")
t = sub(t, "<mark>_____________</mark><em>,</em> 202<mark>[_]</mark>", "October 28<em>,</em> 2026")
t = sub(t, "<mark>[DOMAIN NAME]</mark>", f'<a href="./">{SITE}</a>')
t = sub(t, "<mark>[Company]</mark>", NAME)
t = sub(t, "<mark>[Company Name]</mark>", NAME)
t = sub(t, "<mark>[INSERT PRIVACY POLICY URL — hyperlink]</mark>", f'<a href="privacy.html">{SITE}privacy.html</a>', count=2)
t = sub(t, "<mark>[Cookie Policy / Privacy Policy — hyperlink]</mark>", '<a href="privacy.html">Privacy Policy</a>')
# Explicit template instruction: select one arbitration clause and delete the other. Option A (JAMS) is kept.
t = sub(t, "[<mark>Two alternative arbitration clauses are provided below. Select one and delete the other before "
        "publishing.]</mark> <mark>[OPTION A — JAMS Arbitration]</mark> ", "")
t, n = re.subn(r"<li><p><mark><strong>\[OPTION B — DecisionLayer.*?</ol></li>\n", "", t, count=1, flags=re.S)
assert n == 1
t = mark_pending(unmark(t))
(OUT / "tou-raw.html").write_text(t, encoding="utf-8")
(OUT / "pp-filled.html").write_text(p, encoding="utf-8")
