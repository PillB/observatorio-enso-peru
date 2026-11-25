"""Wrap the filled template bodies in the site's page shell (presentation only: no template text changes)."""
import html
import re
import sys
from pathlib import Path

SRC = Path(sys.argv[1])
PUBLIC = Path(sys.argv[2])
SITE = "https://pillb.github.io/observatorio-enso-peru/"

SHELL = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{title} · Observatorio ENSO Perú</title>
  <meta name="description" content="{title} of the Observatorio ENSO Perú website.">
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'">
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <link rel="canonical" href="{site}{file}">
  <link rel="icon" href="favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="assets/css/app.css">
</head>
<body>
  <a class="skip-link" href="#main">Skip to content</a>
  <header class="site-header">
    <div class="header-inner">
      <a class="brand" href="./" aria-label="Observatorio ENSO Perú, inicio">
        <img src="favicon.svg" width="36" height="36" alt="">
        <span><span class="brand-name">Observatorio ENSO Perú</span><span class="brand-tag">El Niño y La Niña con datos abiertos</span></span>
      </a>
    </div>
  </header>
  <main id="main" tabindex="-1" class="legal">
    <article class="card legal-doc">
      <h1>{title}</h1>
{body}
    </article>
    <p class="legal-nav"><a href="./">Volver al sitio</a> · <a href="privacy.html">Privacy Policy</a> · <a href="terms.html">Terms of Use</a></p>
  </main>
</body>
</html>
"""


def slug_index(body):
    """The template's index links point at the wrong headings after the .docx conversion: point each one at the
    heading with the same text."""
    heads = {re.sub(r"<[^>]+>", "", m.group(2)).strip().lower(): m.group(1)
             for m in re.finditer(r'<h[1-6][^>]*id="([^"]+)"[^>]*>(.*?)</h[1-6]>', body, re.S)}

    def fix(m):
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip().lower()
        target = heads.get(text)
        return f'<a href="#{target}">{m.group(2)}</a>' if target else m.group(0)
    return re.sub(r'<a href="#([^"]*)">(.*?)</a>', fix, body, flags=re.S)


def shape(body):
    body = re.sub(r'<h1 class="unnumbered" id="section"></h1>\n?', "", body)
    body = re.sub(r"<colgroup>.*?</colgroup>\n?", "", body, flags=re.S)  # inline widths the page's CSP blocks   # empty heading from the .docx
    body = re.sub(r"<(/?)h([1-5])", lambda m: f"<{m.group(1)}h{int(m.group(2)) + 1}", body)  # page title is the h1
    return body


pp = (SRC / "pp-filled.html").read_text(encoding="utf-8")
pp = slug_index(pp)
auto = re.search(r'id="(automatic-data-collection[^"]*)"', pp).group(1)
pp = pp.replace('<a href="">automatic data collection</a>', f'<a href="#{auto}">automatic data collection</a>')
pp = shape(pp)
tou = shape((SRC / "tou-raw.html").read_text(encoding="utf-8"))

# The credit footnote that closes each template in General Legal's repository (their README asks to keep it).
CREDIT = Path(sys.argv[3]).read_text(encoding="utf-8").strip().splitlines()[-1]
assert CREDIT.startswith("This template was prepared and made publicly available by General Legal")
pp += f"\n<hr>\n<p>{html.escape(CREDIT, quote=False)}</p>"
tou += f"\n<hr>\n<p>{html.escape(CREDIT, quote=False)}</p>"

for file, title, body in (("privacy.html", "Privacy Policy", pp), ("terms.html", "Terms of Use", tou)):
    body = "\n".join("      " + line if line else line for line in body.strip().splitlines())
    (PUBLIC / file).write_text(SHELL.format(title=html.escape(title), site=SITE, file=file, body=body),
                               encoding="utf-8")
    print(file, len(body))
