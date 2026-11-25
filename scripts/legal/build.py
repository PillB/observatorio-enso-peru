"""Builds the four legal pages of the site from their bodies in scripts/legal/src/.

    python3 scripts/legal/build.py            # writes public/{privacy,terms,privacidad,terminos}.html
    python3 scripts/legal/build.py --check    # exits 1 if a page differs from its source

The bodies started as General Legal's CC0 templates (fill.py and wrap.py reproduce that first, verbatim version);
docs/legal.md lists every change made to them since.
"""
import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = Path(__file__).resolve().parent / "src"
SITE = "https://pillb.github.io/observatorio-enso-peru/"
CREDIT = ('This template was prepared and made publicly available by General Legal, PC ("General Legal"). It is '
          "provided for general reference purposes only and does not constitute, and should not be construed as, legal "
          "advice, or an endorsement or review of any particular transaction in which it is used. Use of this template "
          "does not create an attorney-client relationship with General Legal. General Legal has not reviewed, and takes "
          "no position on, any modifications made to this document or the deal terms it is used to document.")

PAGES = {
    # file: (source, lang, title, page that has the same text in the other language)
    "privacy.html": ("privacy.en.html", "en", "Privacy Policy", "privacidad.html"),
    "terms.html": ("terms.en.html", "en", "Terms of Use", "terminos.html"),
    "privacidad.html": ("privacy.es.html", "es-PE", "Política de Privacidad", "privacy.html"),
    "terminos.html": ("terms.es.html", "es-PE", "Términos de Uso", "terms.html"),
}
UI = {
    "en": {"skip": "Skip to content", "desc": "{t} of the Observatorio ENSO Perú website.", "other": "Español",
           "based": "Based on the <a href=\"https://github.com/General-Legal/legal-templates\">templates of General Legal</a> "
                    "(CC0 1.0), adapted for this Site.",
           "nav": '<a href="./">Volver al sitio</a> · <a href="privacy.html">Privacy Policy</a> · <a href="terms.html">Terms of Use</a>'},
    "es-PE": {"skip": "Saltar al contenido", "desc": "{t} del sitio web Observatorio ENSO Perú.", "other": "English",
              "based": "Basado en las <a href=\"https://github.com/General-Legal/legal-templates\">plantillas de General "
                       "Legal</a> (CC0 1.0), adaptadas a este Sitio y traducidas al castellano. Nota original de General Legal:",
              "nav": '<a href="./">Volver al sitio</a> · <a href="privacidad.html">Política de Privacidad</a> · '
                     '<a href="terminos.html">Términos de Uso</a>'},
}

SHELL = """<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>{title} · Observatorio ENSO Perú</title>
  <meta name="description" content="{desc}">
  <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'">
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <link rel="canonical" href="{site}{file}">
  <link rel="alternate" hreflang="{lang}" href="{site}{file}">
  <link rel="alternate" hreflang="{other_lang}" href="{site}{other}">
  <link rel="icon" href="favicon.svg" type="image/svg+xml">
  <link rel="stylesheet" href="assets/css/app.css">
</head>
<body>
  <a class="skip-link" href="#main">{skip}</a>
  <header class="site-header">
    <div class="header-inner">
      <a class="brand" href="./" aria-label="Observatorio ENSO Perú, inicio">
        <img src="favicon.svg" width="36" height="36" alt="">
        <span><span class="brand-name">Observatorio ENSO Perú</span><span class="brand-tag">El Niño y La Niña con datos abiertos</span></span>
      </a>
      <div class="header-actions"><a class="icon-btn" href="{other}" hreflang="{other_lang}" lang="{other_lang}">{other_label}</a></div>
    </div>
  </header>
  <main id="main" tabindex="-1" class="legal">
    <article class="card legal-doc">
      <h1>{title}</h1>
{body}
      <hr>
      <p class="legal-credit">{based}</p>
      <p class="legal-credit" lang="en">{credit}</p>
    </article>
    <p class="legal-nav">{nav}</p>
  </main>
</body>
</html>
"""


def render(file):
    src, lang, title, other = PAGES[file]
    ui = UI[lang]
    body = (SRC / src).read_text(encoding="utf-8").strip()
    body = "\n".join("      " + line if line else line for line in body.splitlines())
    return SHELL.format(lang=lang, title=html.escape(title), desc=html.escape(ui["desc"].format(t=title)), site=SITE,
                        file=file, other=other, other_lang=PAGES[other][1], other_label=ui["other"], skip=ui["skip"],
                        body=body, based=ui["based"], credit=html.escape(CREDIT, quote=False), nav=ui["nav"])


def main(argv):
    stale = []
    for file in PAGES:
        out = ROOT / "public" / file
        page = render(file)
        if "--check" in argv:
            if not out.exists() or out.read_text(encoding="utf-8") != page:
                stale.append(file)
        else:
            out.write_text(page, encoding="utf-8")
    if stale:
        print("desactualizadas (corra python3 scripts/legal/build.py): " + ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
