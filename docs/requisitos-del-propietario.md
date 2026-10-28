# Observatorio ENSO Perú: owner requirements register (deduplicated)

Compiled 2026-10-17 from `upload/` (22 files, but only **7 distinct texts + 1 image**; the rest are byte-identical duplicates), `download/README.md`, `audit/architecture-decision.md`, and the tail of `worklog.md`.

## 0. Source inventory

| ID | File(s) (md5-identical copies grouped) | Nature |
|---|---|---|
| S1 | `1. Core operating principles.md` | Original master spec (Solarize protocol v1): intent, science rules, contracts, Vite/TS/Tailwind, WebLLM chat, tests, gates |
| S2 | `Pasted Content_1785973735058/813596/831882/849399/865547/1785979419025.txt` (6 copies) | Spec v2: daily 23:37 Lima automation, watchdog, freshness states, **GRD image policy**, tutorial system, no-hardcode rules |
| S3 | `Pasted Content_1785975797612/821678/841302/861609/939526.txt` (5 copies) | Spec v3: expert threshold-policy system, semáforo contract, PDF/email/LLM extraction, Playwright agents, OWASP |
| S4 | `Pasted Content_1785983066845/1785983336775.txt` (2 copies) | Release-readiness audit prompt (live site, click-every-button, screenshots + visual model) |
| S5 | `Pasted Content_1785994615459.txt` | Test/remediation/release-gate controller (deliverable matrix, device list, WCAG 2.2 AA, "equipo GRD" terminology) |
| S6 | `Pasted Content_1786005715907/5907050/5927576/5947119.txt` (4 copies) | Autonomous high-frequency update system (3 temporal layers, fallback graph, preflight hypotheses, one publication path) |
| S7 | `Pasted Content_1786119016929.txt` | VP brief + source-acquisition architect (fresher-than-monthly data, H1–H10 hypotheses, "Dato actual no disponible") |
| S8 | `SOLARIZE SYSTEM PROMPT.md` | End-to-end audit (competing frontends, atomic publication, freshness semantics, tutorial state machine, deterministic assistant, theme, Playwright journeys) |
| IMG | `pasted_image_1785979488111.png` | Photo of a slide/table: GRD trigger thresholds ("Triggers FEN" thumbnail visible at bottom) |
| T | Owner timeline note (relayed) | "make it ready for production"... "world class" |
| W | `worklog.md` | Agent log; reveals owner design directives not in upload/ (palette changes, "equipo GRD" rename) |

Priority key: **P0** = release-blocking/critical-failure condition named by owner; **P1** = core feature; **P2** = quality/robustness; **P3** = nice-to-have / process.

---

## 1. Product intent (invariant)

- P0 Peru-focused, open-data ENSO monitoring + interpretation platform; "Do not replace this goal with a generic weather dashboard, a conventional forecast website, or a backend-heavy application that cannot run on GitHub Pages." (S1 §1.1, S3 §1)
- P0 Four indicator families: SST anomalies, trade/zonal winds, thermocline depth (D20), SOI/pressure (S2 §1). "All four indicator families are implemented or their unresolved gaps are documented honestly." (S1 §17)
- P0 Separate: El Niño/La Niña Costera vs basin ENSO vs official NOAA/ENFEN status vs "Expert-supplied operational traffic-light signals" vs data freshness/quality (S2 §1.2).
- P0 "The website must never imply that it is an official warning service." (S8 §2)
- P1 Current, recent and historical data; maps, charts, animations, timelapses, complete historical tables, CSV downloads (S1, S2).
- P1 Grounded conversational assistant (S1–S3), interactive stoppable/resumable/restartable tutorial (S2 §1.6).
- P1 "Updates automatically every day near the end of the day in Peru" without manual daily intervention (S2 §1.3–1.4).
- P1 Deploy on GitHub Pages; live targets: `https://pillb.github.io/observatorio-enso-peru/`, repo `PillB/observatorio-enso-peru`, branch `main`, env `github-pages` (S4–S8).
- P1 Executive question (S7): can the system get data "more frequently than the monthly reports for each variable" — answered honestly per variable, with a VP blurb (80–120 words) and one-page brief in Spanish.

## 2. Data-integrity rules (no fabrication)

- P0 "No fabricated fallback values." / "No silent fallback substitutions." (S1 §2, S2 §2.3)
- P0 "Contains no hardcoded live observations, current dates, current statuses, freshness claims, or demonstration values presented as real data." (S2 §1.12)
- P0 Synthetic material only under `tests/`, `fixtures/`, `demo/`, visibly labeled; before real data are ready publish containment text **"Datos actuales en proceso de validación"** (S5, S6 §17).
- P0 "Never infer missing numbers from chart pixels" / "Do not infer D20 numerically from plot colors or pixels." (S1 §7, S6 §6.6)
- P0 Never silently forward-fill, substitute another indicator, label unavailable as neutral, "call an approximate local calculation official" (S8 §4.2).
- P0 "Never call a value 'current' when the data retrieval failed or exceeded the configured freshness threshold." (S1 §4.7)
- P0 Never apply a new generation timestamp to unchanged observations; "Do not rewrite observation timestamps" on no-change runs (S5 §2, S6 §8).
- P1 Every observation retains: valid period, retrieval time, publication time, source id, dataset version, unit, region, level/height, aggregation, climatology, preliminary/final flag, quality flag, transformation version (S1 §4.7, S3 §12).
- P1 Timestamps stored in UTC, displayed in `America/Lima` (S1 §4.7).
- P1 Evidence taxonomy for findings: `VERIFIED`, `EXPERT_POLICY`, `DERIVED`, `ASSUMED`, `UNRESOLVED`, `REJECTED` (S2, S3).
- P1 Display-category taxonomy (S8 §4.1): direct observation / official index / locally reproduced index / observatory interpretation / official status / official forecast / internal operational signal / reanalysis / model / interpolation / illustrative / cached fallback / missing. "Do not allow one category to impersonate another."

## 3. Scientific rules

### 3.1 Coastal vs basin
- P0 Separate `coastal_enso`, `basin_enso`, `official_authority_status`, `expert_operational_signal`, `data_quality_status`; "Never infer one solely from another." (S2 §7.1)
- P0 "Never apply ICEN thresholds to a weekly Niño 1+2 observation." "Never equate a weekly Niño 3.4 value with RONI or an official NOAA ENSO declaration." (S2 §7.2)

### 3.2 Indices
- P0 RONI: consume official `RONI.ascii.txt`; "Do not calculate RONI as a simple three-month rolling mean of Niño 3.4." Record ERSSTv5, relative anomaly (tropical-mean subtraction), variance adjustment, 1991–2020 base, overlapping seasons, revisions (S6 §6.3, S8 §4.3).
- P0 ICEN: latest ENFEN methodology (ERSSTv5, Niño 1+2, 1991–2020, 3-month running mean, persistence, provisional/final); distinguish ICEN classification from official ENFEN declaration (S8 §4.4). H5: "ICEN may currently be derived as a simple rolling mean of Niño 1+2 even when the official methodology and source should instead be consumed directly." (S7)
- P0 "Never reuse thresholds from an older index version without verification." (S1 §4.2)

### 3.3 Winds
- P0 Positive u = eastward/westerly; negative u = westward/easterly, after source verification (S1 §4.3). "Wind direction is reversed" = automatic release failure (S1 §16).
- P1 Distinguish actual vs anomaly, surface/10 m vs 850 hPa, zonal vs alongshore vs vector; "Do not label every coastal wind measurement as 'trade winds.'" A local reversal must not classify the whole Pacific (S1, S3 §4.4).

### 3.4 Thermocline
- P0 D20 (20 °C isotherm depth) only when the source defines it; positive anomaly = deeper (S1 §4.4). "Do not assume another isothermal-layer-depth variable is equivalent to D20 without scientific evidence." (S7 §8.5)
- P0 "Do not pretend a coastal D20 index exists if only a low-resolution basin estimate is available." Point values (e.g. 95°W, 0°) labelled with exact location (S1, S3 §6.4).

### 3.5 SOI
- P0 SOI is basin-scale (Tahiti–Darwin). "Do not create or display a variable called 'coastal SOI.'" Chat must correct "SOI costero" (S1 §4.5, §10.4). Fabricated coastal SOI = automatic release failure (S1 §16).
- P0 "Do not apply thresholds from one SOI formulation to another." If the policy was defined for a BoM-style 90-day SOI and the source is NOAA monthly standardized SOI → `POLICY_NOT_APPLICABLE` (S3 §6.5).

### 3.6 Three temporal layers (S6 §4, S7 §6)
- P1 Layer A fast observations (daily OISST, weekly CPC Niño, IMARPE daily/weekly bulletins, TAO); Layer B operational indices (ICEN, RONI, SOI, CPC 850 hPa wind indices, D20); Layer C official authority (ENFEN, NOAA/CPC). "Do not infer an official alert from a rapid observation." Faster observations "do not automatically replace an official NOAA or ENFEN classification."

### 3.7 Forecasts
- P2 Each forecast: issuer, issue date, valid season, probability, verifying index, basis, uncertainty. "Do not transform current observations into an unofficial forecast." (S8 §4.8)

## 4. GRD team expert thresholds ("semáforo")

**Origin:** the image `upload/pasted_image_1785979488111.png` — a phone photo of an on-screen slide titled with columns *Indicador / Región / Condiciones normales / Gatillador / Estatus*, a "Triggers FEN" thumbnail at the bottom. S2 §8 and S3 §6 instruct to preserve the image + hash + exact transcription in `config/threshold-policies/expert-grd-image-v1.yaml`. Supplier is described as a "GRD/climatology/geology expert" (S3 §1.4); the owner later had "experto GRD" renamed to **"equipo GRD"** and the label **"Señal operativa del equipo GRD"** required (S5 §6.6, W task 23/24).

Transcription (image):

| Indicator | Region | Normal | Yellow | Red | Example "Estatus" in image |
|---|---|---|---|---|---|
| ATSM | Niño Costero 1+2 | −0.7 °C to +0.5 °C | "Entre +1.3 y +2.°C" (read as +2.0, digit likely cut) | "Mayor a +2.1°C" | +2.7 °C red |
| ATSM | Niño Global 3.4 | −0.5 °C to +0.5 °C | "> +1.0 a +1.5°C" | "> +1.5°C" | +1.2 °C yellow |
| Vientos Alisios | Niño Costero y Global | Este a Oeste | none | "Oeste a este" | Oeste a este, red |
| Termoclina (20 °C) depth anomaly | Niño Costero | −20 m to +20 m | 30 m to 50 m | "Mayor +50m" | 52 m red |
| Termoclina | Niño Global | −20 m to +20 m | 30 m to 50 m | ">Mayor +50m" | 38 m yellow |
| SOI | Niño Costero y Global | "+7 a -7" | none | "Menor a -7" | −14.50 red |

Rules (S2 §8, S3 §5–7):
- P0 Gaps stay **unclassified**, never green: coastal +0.5–+1.3, +2.0–+2.1, < −0.7; basin +0.5–+1.0, < −0.5; D20 +20–+30, < −20; SOI > +7 "must not be automatically green".
- P0 Wind rule not automated "until region, level, actual-versus-anomaly, duration, magnitude, and coverage are configured."
- P0 Basin policy is for Niño 3.4: "Do not apply it to RONI unless the policy explicitly declares RONI compatibility." Coastal: unresolved whether weekly/monthly Niño 1+2 or ICEN.
- P0 SOI ±7 scale implies a BoM-style SOI (×10); apply only to the exact compatible series.
- P0 The image's example "Estatus" values are demo values, never live data.
- P1 Signal values: `GREEN, YELLOW, RED, UNCLASSIFIED, POLICY_NOT_APPLICABLE, INSUFFICIENT_DATA, STALE_DATA`. Every signal shows value, unit, period, metric, scope, source, policy version, reason, official-vs-expert distinction, freshness, uncertainty.
- P1 Three labels per indicator: `official_status`, `expert_operational_signal`, `data_quality_status`; "Never use color alone" (text + icon/shape + colour-blind-safe styling).
- P1 Spanish labels: "Condición dentro del rango operativo normal", "Señal operativa amarilla/roja", "Sin clasificación en la política experta", "Política no aplicable a esta métrica", "Estado oficial publicado por ENFEN", "Interpretación operativa del observatorio", "Dato preliminar", "Dato desactualizado".
- P1 A research-backed candidate mapping (weak +0.5–1.3, moderate 1.3–2.1, strong 2.1–3.5, extraordinary >3.5) must **not** replace the transcription without recorded approval (S3 §6.1).
- P0 "Do not separately calculate the same GRD signal in Python pipeline, data generator, HTML JavaScript, chart code, chat code" (S7 §23). The browser consumes `operational-signals.json`.
- P0 No alert colour from stale or missing data.

## 5. Freshness, automation, deployment

- P0 Daily run at **23:37 America/Lima** (`cron: "37 23 * * *"`, `timezone: "America/Lima"`), plus `workflow_dispatch` (force_refresh, dry_run, source, publication_mode) and `repository_dispatch: enso-refresh` (S2 §5.2, S6 §14). "Every declared workflow input must map to a tested CLI argument" (`run --source --force-refresh --dry-run --staging-dir --publication-dir --offline --max-source-failures`).
- P0 One reusable workflow, one concurrency group `enso-production-publication`, one staging dir, one publication dir; "Do not commit generated data to `main` merely to trigger another Pages deployment"; no `|| true` (S6 §13–14, S8 §12).
- P1 Watchdog (e.g. every 6 h at minute 17) reading the **live** `health.json`; bounded recovery: one rerun + one source retry, then alert/issue and stop (S2 §5.3, S6 §15, S7 §21). Optional external dead-man monitor; "Do not claim independent monitoring is active until it is configured and tested."
- P1 Per-source freshness SLOs (cadence, release window, latency, grace, stale threshold, revision window); "Never use one global 'stale after N days' rule." "A monthly source does not become stale because it did not change during a daily run." (S7 §16)
- P1 Freshness states: `CURRENT, WITHIN_EXPECTED_CADENCE, NOT_DUE, PUBLICATION_EXPECTED, DELAYED, PRELIMINARY, STALE, FAILED, QUARANTINED, UNKNOWN`. Run outcomes: `UPDATED, NO_NEW_SOURCE_RELEASE, PARTIAL_SOURCE_FAILURE_WITH_VALID_FALLBACK, BLOCKED_BY_DATA_QUALITY, FAILED`; `NO_NEW_SOURCE_RELEASE` is not a failure.
- P0 Stale semantics: "Never present stale data as current"; current card shows **"Dato actual no disponible"**; last valid period shown separately; not used for GRD colour or current chat evidence; historical rows keep true dates (S2 §5.7, S7 §17).
- P1 Separate source availability, retrieval freshness, observation freshness, official-publication freshness, observatory-publication freshness, extraction quality, revision state. "Fallback availability must never be equivalent to successful current extraction." (S8 §3.5, §10)
- P0 Atomic publication: every artifact carries the same `publication_id`, pipeline version, source snapshot, schema version, policy versions, generated_at, Git SHA; "The browser must reject or visibly quarantine mixed-publication artifacts." (S6 §13, S8 §9)
- P1 Failed source never erases last valid snapshot; previous production stays live when a build fails.
- P1 `health.json` generated only from real retrieval evidence; UI derives freshness from it, "not from the browser clock alone" (S2 §5.9).
- P1 Defensive acquisition: UA, HTTPS, connect/read/total timeouts, ≤4 retries, full-jitter backoff, Retry-After, conditional GET, per-host limits, circuit breaker, size/decompression limits, MIME + file-magic, SHA-256, atomic cache, schema fingerprints, HTML-error-page detection (S6 §9). "Robust and persevering" means bounded, "It does not mean retry forever." (S7 §12)
- P1 Fallback graph: primary → equivalent → lower-cadence same metric → last-known-valid → unavailable; explicit prohibited substitutions (Niño 1+2 for ICEN, Niño 3.4 for RONI, surface for 850 hPa, point for basin, other isothermal metric for D20, project signal for official status) (S6 §10, S7 §13).
- P1 Source retrieval order: API → ERDDAP/OPeNDAP/THREDDS/NetCDF/CSV → static dirs → dashboard network → RSS/CMS → HTML → PDF → deterministic extraction → Playwright → OCR → LLM last. Never bypass auth/CAPTCHA/robots/ToS.
- P1 Source candidates to investigate: NCEI OISST ERDDAP (final+prelim), CPC weekly Niño OISST v2.1, CPC RONI, CPC SOI + 3-month SOI, CPC 850 hPa trade-wind indices (W/C/E Pacific), PMEL TAO/TRITON + ERDDAP, GODAS, PSL, ENFEN site + wp-json, SIOFEN/IMARPE BDO (daily) and BS-TLP (weekly) bulletins, NOAA ENSO discussion.
- P1 Source-contract monitor must perform real bounded probes (status, MIME, schema, units, latest date), fail closed on drift (S7 §22, S8 §11).
- P2 Document/email ingestion: deterministic PDF extraction first; LLM extraction only with page + exact evidence text, quarantine, two-path agreement for critical values; email only with authorized mailbox, allowlists, no macro execution (S2 §9, S3 §10–11).
- P1 ADR (`audit/architecture-decision.md`): canonical production frontend is static `public/index.html`; Next.js in `src/` "NO se despliega" and is reference only; pipeline publishes to `public/data/`.
- P2 Data persistence: compare (A) full Pages artifact from live sources, (B) data branch/releases, (C) object storage for grids; no large raw gridded data in repo (S7 §27).

## 6. Frontend, visualization, UX

- P0 "The production browser must not execute raw TypeScript." "Do not use Tailwind Play CDN in production." (S1 §6.2, §16)
- P1 Stack (S1/S2/S3): Vite, TypeScript compiled, Tailwind compiled, semantic HTML, Web Workers; "Inline critical or complete application CSS and compiled application JavaScript in the final HTML when this remains maintainable." S8 instead offers Option A (Next static export) vs Option B (modular static app split into HTML/CSS/JS modules) and demands **one** canonical frontend.
- P1 Information architecture: executive overview, El Niño Costero, basin ENSO, SST, winds, thermocline, SOI/pressure, official vs expert status (+ timelines), historical comparison, maps & animations, data explorer & downloads, methodology & provenance, freshness/source health, tutorial center, assistant (S1 §9.1, S2 §13, S3 §14).
- P1 Current card fields: metric, scope, value, unit, valid period, observation frequency, official status, GRD signal, data-quality status, source, dataset version, climatology, preliminary flag, policy version, uncertainty, sparkline (S2 §13, S3 §14.1).
- P1 Visualizations to evaluate: time series with zero line, documented threshold bands, monthly/seasonal heatmaps, coastal-vs-basin small multiples, Hovmöller, depth–longitude sections, D20 maps, wind vectors, SST anomaly rasters, climatology/percentile views, event-aligned comparisons, timelapses (S1 §9.3). Library chosen by comparison (MapLibre, D3, Plot, ECharts, Plotly, deck.gl).
- P0 "Do not use 3D, animation, interpolation, particles, or pulsing effects merely for decoration." (S1 §9.3)
- P1 Animation controls: play/pause, scrubber, speed, frame date, restart, keyboard, reduced motion, loading + missing-frame states, "No undocumented interpolation" (S1 §9.4).
- P1 Visual integrity: colour-blind-safe diverging palette centred at zero; status not by colour alone; consistent scales; no truncated axes; show gaps; provisional visually distinct; baseline + unit near chart; accessible summaries (S1 §9.5).
- P1 Maps: real spatial source, correct projection/extent, "Continent/coastline underlay for geographic maps", "No basemap under non-geographic plots", legend, attribution, WebGL fallback, accessible data alternative (S5 §6.8). "An index-derived illustration must not visually resemble a measured high-resolution field without a persistent disclaimer." (S8 §16)
- P1 Tables per variable: search, sort, date/region/source/quality filters, pagination/virtualization, export all + filtered, stable schema, provenance; chart/table/CSV/card/chat parity; CSV formula-injection protection (S1 §8, S3 §14.4).
- P1 Failure-state UX for each component: loading/current/preliminary/fallback/delayed/stale/failed/unavailable; messages e.g. "Fuente temporalmente no disponible.", "El último dato válido corresponde al periodo {period}. No se utiliza para representar la condición actual.", "Se detectó un cambio en el formato de la fuente. El dato permanece en validación." (S7 §24)
- P2 Theme switch with persistence across refresh (S8 §13.2 journeys 8–9); emergency disclaimer visible (journey 36).
- P2 Performance budgets: HTML/CSS/JS/initial data, LCP, INP, CLS, low-end mobile; "Do not meet budgets by removing scientific evidence." (S8 §17)

### 6.1 Palette / visual style (owner directives found only in worklog, not in upload/)
- W task 1–16: "paleta teal/ámbar (sin azul índigo)".
- W task 17 (owner request): "estética futurista metálica — azul/plata, iconos SVG bespoke, HUD Iron Man + art nouveau", no emojis, arc-reactor logo with pulse, scanlines.
- W task 22: owner/VLM-driven "deep ocean premium" (navy #0c4a6e, teal #0891b2, crimson #b91c1c), Inter font; task 25 replaced Google Fonts with system stack ("font self-hosted" was the stated goal).
- Constant across all: no indigo, no emojis, bespoke SVG icons, dark mode.

## 7. Language and tone

- P0 All public content in "formal, clear, internationally understandable Spanish suitable for a Peruvian public, technical, and institutional audience." (S1 §9); final reports in Spanish; technical identifiers may be English (S7).
- P1 "Do not use sensationalistic disaster language." (S1 §9)

## 8. Tutorial

- P1 Guided tour + persistent reference/methodology centre; "Do not force the tutorial on every visit"; persistent **"Ayuda y tutorial"** control (S2 §12).
- P1 Library comparison: Driver.js (strong candidate), Shepherd.js, Intro.js, native — licence, a11y, focus, mobile, pause/resume.
- P1 Thirteen modes: "Inicio rápido", "Recorrido completo", "El Niño Costero", "ENSO de escala cuenca", "Temperatura superficial del mar", "Vientos", "Termoclina", "SOI y presión", "Semáforos y estados oficiales", "Mapas y animaciones", "Tablas y descargas", "Fuentes, vigencia y metodología", "Uso del asistente conversacional".
- P1 Controls: start, pause, resume, back, next, skip, exit, restart module, restart all, resume from last step (after reload), clear progress; visible progress.
- P1 Versioned `TutorialState` (id, version, mode, status, current step, completed steps, timestamps, data snapshot, interface version); restore pre-tour state on cancel.
- P1 Stable `data-tour-id` selectors; handle async/missing targets, route changes, mobile, focus restore, reduced motion, screen-reader announcements; "Never conceal a critical source-failure warning."; "Do not repeatedly target the entire sidebar." (S8)
- P1 Progression tied to real user actions (S8 §14). Dynamic values bound to data ("Do not hardcode the current number into tutorial prose"); scientific text from canonical methodology registry.
- P2 Expert editorial review schema (reviewer, review date, next review); "No tutorial section is scientifically approved merely because it was generated by an LLM."
- P2 Isolated chatbot demo step with sample question "¿Qué indica el valor más reciente de Niño 1+2 y cuál es su periodo de validez?"; not written to real chat history; no paid remote call.

## 9. Assistant / chatbot

- P0 "grounded interpretation layer, not as the source of numerical truth"; deterministic query + code-computed statistics before any LLM; evidence package; validate numbers/dates/claims; cite evidence IDs and source dates (S1 §10).
- P0 Must: formal Spanish; state valid period; distinguish data/interpretation/uncertainty and official vs GRD; correct "SOI costero"; refuse to invent values; no deterministic disaster causation; no official alerts; refer to ENFEN/SENAMHI/INDECI/CENEPRED; no long-range forecasts; resist injection in retrieved data; never reveal prompts/secrets.
- P1 Runtime (S1–S3): preferred in-browser WebLLM/WebGPU in a worker with download-size disclosure; benchmark ≥3 models (Llama-3.2-3B/1B MLC, Phi mini, Qwen/Gemma) on Spanish, faithfulness, injection; default + low-resource + quality tiers; deterministic fallback "Never present a non-LLM fallback as an LLM response"; remote only via proxy, no tokens in Pages.
- P1 S8 overrides honesty: "It is not an LLM unless a real model is integrated"; answer from the current validated publication only; no mixing publications; no fallback described as current; render as text, no unsafe HTML.
- P1 Score rubric (S1 §12.4): avg ≥ 20/24, correctness ≥ 3/4 each, no fabricated value, no uncited number.
- P2 Version-controlled system prompt + user template.

## 10. Accessibility, responsive, security

- P0 WCAG 2.2 AA baseline; reflow at 320 CSS px; no critical/serious axe violations; keyboard, focus, headings, labels, status announcements, non-colour status cues, chart/map/table alternatives, 200 % zoom, reduced motion, touch targets (S5 §6.12, S8 §17).
- P1 Device matrix: 320×568, 390×844, iPhone landscape, 360×800, 412×915, Android landscape, iPad Mini & Pro portrait/landscape, desktop Chromium/Firefox/WebKit; state that profiles are emulations. No page-level horizontal overflow; "use global overflow clipping as the only responsive fix" is forbidden.
- P0 No secrets/tokens in bundles; CSP compatible with workers/WASM; SRI; dependency pinning/lockfiles; secret & vuln scanning; sanitization; no unsafe `innerHTML`; `noopener`; CSV-injection mitigation; least-privilege workflow permissions (S1 §11, S8 §17).
- P0 Never test/attack NOAA, ENFEN, IMARPE, GitHub, map or model providers.

## 11. Testing, verification, release process

- P1 Strict Red → Green → Refactor; tests before fixes; assert behaviour not implementation; healer may not weaken assertions; no arbitrary sleeps; retried-to-pass critical test = FLAKY.
- P1 Playwright `@playwright/test` user-level tests via `getByRole/getByLabel`; "Do not use internal application functions as the primary test path." (S8 §13); 36 listed user journeys; fault injection list (404/500/malformed JSON/mismatched publication ID/stale/NaN/offline/no localStorage/JS disabled...).
- P1 Visual forensics with an actual image model, findings corroborated by DOM/CSS evidence; otherwise `BLOCKED_VISUAL_REVIEW`.
- P1 Final verification on the live Pages URL; deployed SHA = intended SHA; publication ID verified; fresh + returning-user cache contexts.
- P1 Two consecutive quiet independent rounds; max rounds 3 (S1–S7) or 5 (S8).
- P1 Verdict vocabulary: `READY_FOR_CLIENT_ACCEPTANCE / CONDITIONALLY_READY / NOT_READY / AUDIT_ONLY_NO_DEPLOY_PERMISSION / BLOCKED_*`; "Do not report a feature as complete merely because code exists."; README/worklog claims are not proof.
- P2 Documentation: README, CITATION.cff, licence notes, docs (architecture, methodology, source catalog, threshold register, model evaluation, limitations, operations, ledgers); Python type hints/docstrings, TSDoc; comments explain why; no TODO/placeholder in production paths.
- P2 Final reports in Spanish with mandated section lists (S1 §15, S2 §20, S3 §21, S4 §20, S5 §20, S6 §22, S7 §P).

---

## 12. Contradictions and tensions between requirements

1. **Assistant runtime.** S1–S3 want an in-browser WebLLM generative assistant (benchmarked models, WebGPU, tiers). S8 §15 is titled "Deterministic assistant" and says "It is not an LLM unless a real model is integrated." Resolution needed: deterministic guide is acceptable only if honestly named; LLM is still the stated preferred end state.
2. **Frontend stack.** S1–S3 require Vite + compiled TS + compiled Tailwind + Web Workers. The ADR (`audit/architecture-decision.md`) keeps the hand-written monolithic `public/index.html` (~124 KB, inline JS/CSS, no TS build). S8 offers Option B "modular static application" (split into modules). The ADR satisfies "one canonical frontend" but not the TS/Vite/Tailwind requirement or S8's modularisation.
3. **Validation-round limits.** "maximum of three" rounds (S1–S7) vs "exactly four macro-rounds" + "Maximum complete validation rounds: five" (S8).
4. **Schedule syntax.** S2/S6 require `timezone: "America/Lima"` in cron; repo uses `cron: '37 4 * * *'` UTC (same wall-clock, Peru has no DST). Equivalent in effect; verify whether GitHub supports the `timezone` key before adopting.
5. **Watchdog cadence.** S2 suggests "every six hours at minute 17" (off-hour), repo watchdog runs at minute 0 (`0 6,12,18,23`), which conflicts with S1 "Schedule away from the beginning of the hour".
6. **Palette history.** teal/amber → blue/silver Iron-Man HUD with pulsing arc reactor + scanlines → deep-ocean navy/teal/crimson. The HUD effects (pulse, scanlines, glow) conflict with S1 "Do not use ... pulsing effects merely for decoration".
7. **Fonts.** Inter via Google Fonts (task 22) vs "font self-hosted" (task 25, implemented as system stack instead). Neither choice conflicts with the spec, but "self-hosted" was not literally done.
8. **"Never show stale data" vs history.** Owner phrase is reconciled by S2/S7: stale is allowed in history when dated, never as current. Implementation must follow the refined reading.
9. **Fresher data vs official status.** Owner/VP want "fresher-than-monthly" data; S6/S7 forbid letting fast observations change official or index-layer values. Fast data informs observations only.
10. **Expert policy vs metric fit.** The image mixes region labels (Niño 1+2, Niño 3.4) with unspecified metric/aggregation; S3 forbids applying it to RONI or to an incompatible SOI scale, yet the product needs a visible GRD signal. Gaps and N/A must be accepted as visible outcomes.
11. **Tutorial module list.** S2 prescribes 13 named modes ("Inicio rápido"... "Uso del asistente conversacional"); the implemented 13 modules (worklog task 27) are a different list (Bienvenida, Navegación, Tema claro/oscuro, etc.) and omit Mapas y animaciones, SOI y presión, Fuentes/vigencia.
12. **Evidence-category vs "health = real".** S8 says cached/manual official status must show as degraded; worklog shows `config/enfen-status.json` manual fallback powering "Alerta de El Niño Costero" in the header like a live official status.

## 13. Requirements that look unmet or at risk (from worklog + quick repo checks; to be verified)

| # | Requirement | Observation | Severity guess |
|---|---|---|---|
| U1 | Browser must not recompute GRD signal (S7 §23) | `public/index.html` lines ~655–912 define `evalCoastalSST/evalBasinSST/evalThermocline/evalSOI` and classify in the browser | MAJOR |
| U2 | Basin GRD policy not applied to RONI unless declared compatible (S3 §6.2) | `evalBasinSST(STATUS.basin.roni)`; header showed "GRD: Amarillo" from RONI 1.04 | MAJOR (scientific) |
| U3 | No D20 substitute without evidence (S7 §8.5) | D20 = GODAS `dbss_obil` "ocean isothermal layer depth", labelled "proxy D20"; basin-only (Niño 3.4 box), no coastal D20 although the image has a coastal row | MAJOR |
| U4 | SOI ±7 policy only for compatible formulation (S3 §6.5) | Source is PSL standardized monthly SOI (±~3 scale); last value 0.7 dated July 2025 (stale by >1 yr) | HIGH (misclassification + stale) |
| U5 | ICEN consumed or reproduced per ENFEN method, not naive rolling mean (S7 H5, S8 §4.4) | Worklog 25: "ICEN: calculado como media móvil de 3 meses de Niño 1+2" from PSL CSV (PSL base period/dataset vs ERSSTv5 1991–2020 not confirmed) | MAJOR |
| U6 | Fallback official status shown as degraded (S8 §3.5) | ENFEN status from manual `config/enfen-status.json` when SIOFEN is blocked; displayed as official alert | HIGH |
| U7 | Freshness per source / no stale as current | As of 2026-10-17: NOAA advisory dated 9 July 2026, u850 last 2026-02, D20 2026-06, SOI 2025-07; need confirmation that cards show "Dato actual no disponible" | HIGH |
| U8 | One canonical scheduled pipeline (S8 §12) | Both `daily-data-update.yml` and `daily-refresh.yml` exist, plus `pipeline.yml`, `_update-data.yml`, `deploy-pages.yml` (check push-triggered redeploys of stale data) | MAJOR |
| U9 | Vite/TS/Tailwind build; no raw TS; modular code | Single inline-JS `public/index.html`; Next.js app still in `src/` (undeployed) | MAJOR vs spec (ADR accepted deviation) |
| U10 | Real SST raster maps / Hovmöller / timelapses from gridded data | Maps are "Síntesis ilustrativa a partir de índices observados" (index-derived illustration); OISST grids not integrated | MAJOR |
| U11 | Tutorial: persist versioned state, 13 prescribed modes, action-driven, Driver.js-class evaluation | localStorage keys `enso-tutorial-step/paused/completed/active` only, no version; module list differs | MODERATE–MAJOR |
| U12 | Grounded generative assistant (S1) | "Guía determinista de datos" keyword guide; no WebLLM | Acceptable only as honest fallback |
| U13 | Playwright user-level tests, not internal functions (S8 §3.7) | Worklog validation used `window` globals / `navigate()` style checks and Next.js dev server for "local validation" while production is `public/index.html` | MAJOR (evidence quality) |
| U14 | Publication coherence enforced in browser | Verify frontend rejects mixed `publication_id` across `status.json`, `health.json`, `all-series.json` etc.; `sources.json` + `source-registry.json`, `quality.json` + `data-quality.json` duplicates suggest legacy parallel artifacts | MODERATE |
| U15 | No decorative animation | Arc-reactor pulse, scanlines, glow from HUD redesign may survive | MINOR |
| U16 | External dead-man monitor | Not configured (documented only) | MINOR (must not be claimed) |
| U17 | High-frequency sources (OISST daily ERDDAP, CPC weekly, IMARPE BDO/BS-TLP, TAO) | Weekly SST present (`weekly-sst.json`); daily OISST, IMARPE bulletins, TAO not evident | MAJOR for VP claim |
| U18 | Worklog claims "READY_FOR_CLIENT_ACCEPTANCE" repeatedly | Specs say README/worklog claims are not proof; the items above contradict readiness | process |

## 14. Pure tooling / process chatter (not product requirements)

- `download/README.md`: "Here are all the generated files." (artifact of a prior tool export).
- Role-play preambles ("You are the principal ... architect") in every prompt; "Do not reveal private chain-of-thought".
- Agent topology/role names (planner, generator, healer, breaker, verifier, orchestrator, graph_memory_manager...), Solarize jargon (Graph Memory, STORM, fan-out/fan-in, Loop Engineering, held-out retrospection, link to `PillB/solarize_skill`).
- Authorization gates and verdict codes (`AuthorizationContext`, `BLOCKED_BY_MISSING_AUTHORIZATION`, `AUDIT_ONLY_NO_DEPLOY_PERMISSION`, ZIP comparison).
- Prescribed audit-artifact file lists (`audit/tester/*.json`, `audit/freshness-and-automation/*`, `docs/solarize/...` ledgers), typed audit records (DeliverableRecord, DefectRecord, ScreenshotRecord, VisualFinding, ChangeRecord, PendingRecord...).
- Final-report section templates in Spanish.
- Payment-sandbox rules in S4 (site has no payments).
- S6 trailer "Pre-simulation improvement rounds" / "Spirit-preservation verdict" (prompt-engineering notes left in the paste).
- S7 opening run-on sentence ("TheVP has asked for a blurb...") is the owner's framing of the VP deliverable; the VP blurb/brief is a one-off report, not a site feature.
- Worklog material: GitHub device-auth codes, VLM ratings ("8/10"), test counts, commit hashes.
- Duplicate pastes: 15 of 21 text files are byte-identical copies.

## 15. Disaster memory ("Memoria de desastres", added October 2026)

Requirements from the owner's thread on past climate disasters (relayed 2026-10-26/27). The method, sources and
limits are in [`memoria-desastres.md`](memoria-desastres.md); the source register is
[`catalogo-fuentes.md`](catalogo-fuentes.md) and the licences, [`atribucion-licencias.md`](atribucion-licencias.md).

| ID | Requirement (owner's words, condensed) | Status | Where it is met |
|---|---|---|---|
| M1 | Map every past climate disaster in Peru, exhaustively, from every kind of source: academic work, news, forums and social posts, images, newspaper and magazine archives (also scanned old newspapers), radio, research centres, think tanks, institutions and datasets | PARTIAL | 146 795 records from DesInventar, SINPAD, COEN, IDMC, NASA GLC, GLOF, 44 news outlets, Chronicling America (US newspapers 1836-1963) and curated archives back to 1559 (`memoria-desastres.md` §Fuentes). Not used, with the reason: forums and social networks, radio and TV archives (need keys or registered apps), paywalled or bot-walled archives (never bypassed), outlets that refuse AI use, and Peru-only servers (Biblioteca Nacional), which go to the Peru collector |
| M2 | Test the expert's claim that Peru has done little prevention since the 1990s | DONE | «¿Se sabía antes?» (emergencies where the hazard was already documented, compared with chance) and the evidence section with its verdict «en parte cierto» (`memoria-desastres.md` §¿Se sabía antes?, §Evidencia) |
| M3 | Every record georeferenced and with its provenance | DONE | `Ubigeo`, `Latitud`/`Longitud`, `PrecisionGeo`; `Fuente`, `FuenteCita`, `Licencia`, `FuentesAdicionales`; per-source URL, licence, date and SHA-256 in `data/historico/fuentes.json` |
| M4 | The prevention team's dashboard columns (Date, DangerType, Ubicacion, Distrito, Provincia, Departamento, Descripción, DuraciónEvento, Ubigeo, TipoEvento, Fuente, Latitud, Longitud) plus metadata | DONE | The first 13 columns of `eventos.csv`, with their exact names, plus 50 metadata columns (among them the populated place and the ANA watershed); `diccionario.csv` documents all 63 with their fill rate per source |
| M5 | A historical tab with insights, predictions and risk alerts per city, district, province, department and region | DONE, with a caveat | `#/memoria`: map, area profiles, ranking and «alerta según la historia»; indicator CSVs per district, province, department and macro-region (cities are their districts). "Predictions" are past frequencies with their intervals, validated out of sample, not forecasts; the official alerts remain ENFEN's, SENAMHI's and INDECI's (P0 in §1) |
| M6 | Plan, research, validate, root-cause analysis and edge cases, in several exhaustive rounds | DONE | Two independent review rounds; their findings became the quality rules and reader fixes (`memoria-desastres.md` §Reglas de calidad) |
| M7 | Research best practices and reference dashboards for the tab | DONE | Design after DesInventar, INFORM and SIGRID (`memoria-desastres.md` §La pestaña) |
| M8 | Sources, source handling, documentation and architecture diagrams homologated across threads, scripts, docs and code | DONE | `fuentes.json` → `catalogo-fuentes.md` and `atribucion-licencias.md`; architecture annexes A9 and A11; `python -m tools.build_registry --check` and `python -m tools.architecture --check` in CI |
| M9 | Reliability and methodology validated with established, science-based methods and independent red teaming; interpretation and how to use the risk tab, so every figure comes from the data with a valid method | DONE | Wilson, quasi-Poisson and Poisson dose-response; out-of-sample AUC with cluster bootstrap, El Niño replication, Brier skill and reliability, great-Niño repetition, sensitivity (`memoria-desastres.md` §Validación, §Cómo usar los indicadores); in the tab, «Cómo usar esta pestaña» and «¿La historia anticipa lo que vino después?» |
| M10 | Manual steps go to the Peru server process | DONE | Peru-only servers are in the source registry for the Peru collector (`servidor-peru.md`) |
| M11 | Request frequency: follow each site's guidelines; Peruvian public institutions (.gob.pe, .mil.pe) exempt from robots.txt `Disallow` | DONE | `enso.reach.Robots`; at least 5 s between requests and the site's `Crawl-delay`; other hosts' robots.txt respected (`memoria-desastres.md` §Reproducir y actualizar) |
| M12 | IDMC through its own API | DONE | `IDMC_CLIENT_ID` secret; without it, the HDX export seed |
| M13 | Long downloads run as a GitHub Actions job | DONE | `.github/workflows/memoria-cosecha.yml` (`memoria-desastres.md` §Cosecha en GitHub Actions) |
