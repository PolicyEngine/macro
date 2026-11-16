# Redesign r12 — page map and consolidation

Stacks on #263 (`vahid/model-pages-redesign`). Designed with Fable 5.2 from a
blank page; deviations from Fable's spec are noted with the reason.

## Global shell (owned by session 1, `site_nav.py` + `style.css`)

- **No breadcrumb bar** anywhere. `site_nav.crumbs()` is gone; `render` strips
  any old `<nav class="crumbs">` it finds.
- **Header**: 56px, sticky, translucent white (dark: near-black) with blur and
  a hairline. Brand left (the brand is the way home — no Home tab), three
  section tabs with icons, GitHub icon and one primary button on the right.
  - Forecasts (`forecasts` icon) → /forecasts (Economy pages highlight it)
  - Models (`models`) → /models (model, paper and report pages highlight it)
  - Use (`use`) → /connect
  - Button "Run a model" → /connect
  - Fable proposed Economy, Record and Glossary as tabs too. Not taken:
    `site_contract.check_economy_navigation` forbids a second global tab over
    the Forecasts section, Record is a section of /forecasts, and a glossary
    is a footer utility on product sites.
- **Phone (≤720px)**: brand + button on top; the three tabs become a fixed
  bottom tab bar (icon over label). CSS only.
- **Footer**: four columns — Product (Forecasts, Models, Use, Release notes),
  Models (all seven), Trust (Where models fail, Same question, Papers,
  Glossary), Project (PolicyEngine, GitHub, Report an issue, Contact) — then
  one legal row.
- **One icon system**: Lucide, inline SVG, `site_nav.ICONS` + `icon(key)`.
  `MODEL_ICONS` maps each model id to its icon so every surface agrees:
  pe-microsim `calculator`, obr-macro `landmark`, boe-svar `activity`,
  frb-us `building`, us-hank `users`, psl-og `hourglass`, define-uk `leaf`.
- **Tokens** (appended "Shell v3" block in style.css): type scale
  12/14/16/18/24/32/48 (`--t-*`), spacing 4…96 (`--s-*`, unchanged names),
  section rhythm `--section-y` (96px desktop, 56px phone), card radius 12,
  hover lift 2px. Title bands (`.model-hero`) are light, not teal.

## Information architecture

| Section | Page | Fate |
|---|---|---|
| Home | `/` | Rebuilt: hero + fan, scoreboard strip, model grid, hub diagram, Use band |
| Forecasts | `/forecasts`, `/forecasts/us`, `/economy*`, `/notes/*` | Session 3 |
| Models | `/models` | One page: chooser, matrix, joins diagram, trust, papers |
| | `/models/compare` | Kept as the only Models subpage ("Same question"; own tests + data) |
| | `/models/side-by-side` | → `/models#compare` (308) |
| | `/models/combine` | → `/models#joins` (308) |
| | `/models/validation` | → `/models#trust` (308) |
| | `/models/papers` | → `/models#papers` (308) |
| | 7 model pages × 4 tabs + papers/reports | Session 2 |
| Use | `/connect` | Session 3 |
| Utility | `/glossary`, `/contact` | Tidied; footer only |

Home's "where each model fails" rows move to `/models#trust` (their one home).
Home's three join pipelines become one hub-and-spoke diagram; the detail lives
at `/models#joins`.

## Caveat homes (each stated once, in full, here)

- Forecast record "six forecasts from three rounds are not a track record" →
  home scoreboard strip (summary) and /forecasts (full).
- Per-model verdicts (exact for rules, anchored, partial replication,
  replicates, calibrated, deltas only, no forecast skill) → `/models#trust`.
- OBR emulator: the ~4% free-running GDP figure is the emulator's error, never
  OBR forecast error → /obr/validation (session 2); `/models#trust` says
  "weak free-running" only.
- No US macro bridge; US reforms are scored statically → `/models#choose`
  (dead end in the chooser) and the joins diagram.
