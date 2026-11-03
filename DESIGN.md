# PolicyEngine Macro — design spec

Status: binding for the redesign (branch `vahid/dashboard-redesign`). Phase 1 (this spec, the
tokens and the shell) is implemented; phases 2–4 implement against it and the QA pass checks
against §10. Where something here conflicts with a hard content rule (§1), the content rule wins:
flag it on the PR rather than improvising.

Direction in one line: **a calm, evidence-first research site that reads like a dashboard**: a
dark teal header band with the four views, a teal title band per page, a white sticky sub-tab
row, then white cards on a grey canvas, each with a short title, one-line lede, the figure or
table, and the long explanation one click away. The look borrows from two dashboards, the
tourism demand dashboard (band, underline tab rows, KPI tiles, chips, callouts, expanders,
"On this page" rail) and the UK Autumn Budget 2026 dashboard (teal title bar, intro card with a
left accent, entry cards with icon badges and an "Explore →" button). It takes their patterns,
not their code or branding. **Macro's own explanation style stays**: the two-sided StepPanel
(numbered steps left, sticky figures panel right, §4.9) is the primary layout of model
Overview, Methodology, Validation and Code tabs.

The stack does not change: static HTML, one global `style.css`, Python generators, `site_nav.py`
for the shell. URLs do not change (vercel `cleanUrls` and the redirects in `vercel.json` depend
on them).

---

## 1. Hard content rules (non-negotiable)

1. **Each fact once.** Every number and every finding has one home page and one home section
   (§7.0 lists the homes). Everywhere else it is a link to that home (`<a href="/obr/validation#caveats">`),
   not a restatement. A summary card may name the finding in words ("a benchmark, not a
   validation") and link to it; it may not repeat the figure. The one allowed duplicate is the
   StepPanel's `.meth-panel` / `.meth-inline` pair (§4.9): the same figures, but only one of the
   two is ever visible at a given width.
2. **Every model keeps its verdict and its failure statement**, in its own words, on its
   Overview (one line, linked) and in full on its Validation tab. No redesign step may drop,
   soften or bury a "no skill", "by construction", "does not transmit", "inputs, not results" or
   "deltas only" statement. Shortening is allowed; deleting is not.
3. **No tick/✓ badges or icons** on selected items, anywhere. Selected = fill + border
   (`aria-current`, `aria-selected`, `aria-pressed`, `.is-selected`).
4. **Neutral language.** Never "poor"/"rich": say lower-income / higher-income households, or
   bottom / top income decile, or by wealth. No advocacy, no recommendation dressed as a finding,
   no comparisons framed as wins over another institution.
5. **Sentence case** for every heading, tab, button, chip and caption. Proper nouns and model ids
   keep their case (`boe-svar`, `FRB/US`, `OG-UK`). Eyebrows (`.kicker`) are rendered uppercase by
   CSS; write them in lower case in the markup.
6. **Accessibility.** AA contrast for all text (§2.2), a visible focus ring on every interactive
   element (including on the dark bands), `aria-label` or `<title>/<desc>` on every chart,
   decorative icons `aria-hidden="true"`, link text that makes sense alone, one `h1` per page and
   no skipped heading levels (the tests enforce both).
7. **375 px wide, no page-level horizontal scroll.** Wide tables, code and tab rows scroll inside
   their own wrapper (`.table-scroll`, `.codeblock`, the tab rows).
8. **No `<text>` in a scaling SVG that becomes unreadable.** An SVG drawn with a `viewBox` at
   `width: 100%` scales its text with it: an 800-unit chart at 375 px renders 11 px ticks at
   ~5 px. Rule: any label must render at **≥ 11 px at 375 px** (and in a narrow StepPanel
   column). The site's one approach is §6.3: labels are HTML laid over the SVG.
9. **Caveats are shortened, never deleted.** Long text may move behind an expander (§4.5).

---

## 2. Tokens

All tokens live in the `:root` block at the top of `style.css` (section 0). That block is the
only place a colour value may be written; page CSS and generators use the role names. The
upstream design system is `vendor/ui-kit-tokens.css` (@policyengine/ui-kit 0.12.1, vendored,
do not edit): its `--primary`, `--border`, `--card`, `--chart-*`, `--foreground` etc. are the
base, and `style.css` restates the teal and gray scales it needs because ui-kit only exposes them
in a Tailwind layer a static page cannot read.

### 2.1 Palette and roles

| Role token | Value (light) | Use |
|---|---|---|
| `--canvas` | `--gray-50` #F7F9FB | page background behind cards |
| `--surface-card` | `--card` #FFFFFF | cards, tab rows, panels |
| `--surface-sunken` | `--gray-100` #F2F4F7 | code blocks, tracks, hover fill |
| `--surface-tint` | primary 7% on white | info callout, chosen sub-tab, chip-brand, icon badge |
| `--hairline` / `--hairline-strong` | #E2E8F0 / #CBD5E1 | card borders, rules / axes, stronger borders |
| `--text-strong` | #101828 | headings, values in tables |
| `--text-body` | #344054 | running text |
| `--text-muted` | #475569 | secondary text, ledes, labels |
| `--text-faint` | #5B6878 | **floor for small text** (captions, ticks, eyebrows) |
| `--link` / `--link-hover` | `--primary` #2C7A7B / teal-700 #285E61 | links, active sub-tab text, KPI value |
| `--band-bg` | teal-800 #234E52 | header band, footer |
| `--band-bg-2` | teal-700 #285E61 | pathway + title band |
| `--band-text` / `--band-text-dim` | #FFFFFF / teal-100 #B2F5EA | text on the bands |
| `--band-accent` | teal-200 #81E6D9 | chosen view-tab underline (on the band only) |
| `--warn-bg` / `--warn-line` / `--warn-ink` | #FFF7ED / #FDBA74 / #9A3412 | caution callout and chip |
| `--teal-300`, `--teal-500`, `--gray-400` | | **fills and strokes only, never text** |

Legacy aliases (`--ink`, `--paper`, `--paper-dim`, `--paper-faint`, `--brand`, `--brand-strong`,
`--brand-deep`, `--line`, `--line-soft`, `--surface`, `--brand-wash`, `--chart-s2`, `--amber`)
still resolve, onto the roles above, so the ~100 page-local `<style>` blocks keep working. **New
CSS uses role names.** Phase 2/3 replace aliases as they touch a page; nothing new may use them.

Rules: colour identifies a series, a model family or a state. It never means good or bad: no
red/green verdict colours. The verdict is in words (§1.2).

Dark theme: the site follows `prefers-color-scheme` (the dark block in `style.css` mirrors
ui-kit's dark set; section 5.13 adds the v2 roles). Every new role needs a dark value there.

### 2.2 Contrast (measured)

white on teal-800 9.9:1 · white on teal-700 7.3:1 · teal-100 on teal-800 7.6:1, on teal-700 6.2:1 ·
white 92% on teal-700 6.4:1 · primary on white 5.0:1 · teal-700 on white 7.3:1 · text-faint on
white 5.6:1, on canvas 5.3:1 · text-muted on white 7.6:1 · warn-ink on warn-bg 6.9:1 ·
series-us #026AA2 on white 6.0:1. `--teal-500`/`--chart-1` is 3.5:1: lines and fills only.

### 2.3 Type

Inter (vendored) for everything except h1/h2, which are serif (`--serif`: Source Serif 4 if
present, then Georgia, Cambria, Times; nothing extra is downloaded). JetBrains Mono (vendored)
for code, ids, eyebrows, ticks and the title band's subtitle line.

| Token | Size | Use |
|---|---|---|
| `--fs-label` | 12 px | **minimum size**: eyebrows (uppercase, +0.08em), chart ticks, footnotes |
| `--fs-small` | 13 px | chips, sub-tabs on a phone, stat labels, captions |
| `--fs-body-sm` | 14 px | tabs, tables, callouts, expander bodies, panel text |
| `--fs-body` | 16 px | running text, title-band lede |
| `--fs-lede` | 17 px | intro sentence on the home intro card |
| `--fs-h3` | 18 px, 600, Inter | sub-heading in a card, step title |
| `--fs-h2` | 21–26 px, 600, serif | card (section) title |
| `--fs-hero-sub` | 23–32 px, 600, serif | title-band h1 |
| `--fs-hero` | 28–38 px, 600, serif | homepage h1 |
| `--fs-stat` | 32 px, 650, tabular | stat tile value |

Numbers in tables, tiles and panels are tabular (`font-variant-numeric: tabular-nums`, `.num`).
Minus is U+2212 in generated numbers.

### 2.4 Spacing, radius, elevation, geometry

- Spacing steps only: `--s-1`…`--s-9` = 4, 8, 12, 16, 24, 32, 48, 64, 96 px.
- `--gutter` (canvas edge to card, 12–40 px), `--card-pad` (16–32 px), `--gap-cards` (16–24 px).
- Radius: `--radius-card` 14 px (cards, tiles, panels), `--radius` 10 px (callouts, code,
  inner panels), `--radius-sm` 6 px (tracks), 999 px (chips, buttons, segmented switches).
- Shadows: `--shadow-card` (hairline + soft drop) on every card; `--shadow-raised` on the
  StepPanel panel and hovered entry cards. No gradients on cards.
- Shell geometry: `--nav-h` 56 px (header band height = top of the sub-tab row), `--subnav-h`
  48 px, `--sticky-top` = both + 16 px (top of the StepPanel panel and the rail). **Every sticky
  offset and `scroll-margin-top` reads these**; no hard-coded pixel offsets.
- Motion: 150 ms colour/background transitions, 300 ms for StepPanel state. `prefers-reduced-motion`
  disables all of it (existing rule).

---

## 3. Shell (emitted by `site_nav.py` on all 110 pages; owned by the design lead)

Order on every page:

```
<header class="nav">          header band: brand + primary view tabs     sticky, top 0
<nav class="crumbs">          pathway, first line of the title band      (not on /)
<main id="top">
  <section class="hero model-hero">   title band: h1 · subtitle · lede   scrolls away
  <nav class="model-tabs"> | <nav class="economy-subnav">  sub-tabs      sticky, top --nav-h
  <section class="band">…     cards on the canvas
</main>
<footer class="foot foot-bar">  one row on the band colour
```

### 3.1 Header band + primary view tabs (`.nav`, `.brand`, `.nav-links`)

- One dark row (`--band-bg`, `--nav-h` high), sticky. Left: the PolicyEngine mark on a white
  chip + "PolicyEngine Macro" in serif (the word mark hides below 640 px; the link keeps
  `aria-label="PolicyEngine Macro home"`). Right: the four views from `site_nav.DESTINATIONS`
  (Home, Models, Forecasts, Use, in that order; `site_contract` enforces Home first and the
  `>Forecasts</a>` label) and the GitHub icon (hidden below 420 px; GitHub is in the footer).
- Each view tab: 16 px stroke icon (`site_nav.VIEW_ICONS`, `aria-hidden`, shown from 880 px) +
  label. Chosen view = `rgba(255,255,255,.10)` fill + 3 px `--band-accent` underline on the
  band's bottom edge, weight 600. `aria-current="page"` on the section's own index page,
  `aria-current="true"` on every other page in the section (`site_nav.section()` decides:
  model, paper and report pages → Models; `/forecasts`, `/economy/**`, `/notes/**` → Forecasts;
  `/connect` → Use; `/contact` → none).
- The tab row scrolls sideways inside itself if it ever runs out of room; the page never does.
- Never put `/economy`, `/contact`, `/notes` or `/validation` in the header
  (`site_contract.check_economy_navigation`).

### 3.2 Pathway (`.crumbs`, generated by `site_nav.crumbs()`)

Mono 12 px on `--band-bg-2`, links underlined in teal-100, current page white, `/` separators.
Hierarchy comes from `CRUMB_PARENTS` / `PAGE_NAMES` (reading order, not URL order: model and
paper pages under Models, the data hubs and notes under Forecasts). Maximum four segments. Not
emitted on the homepage.

### 3.3 Title band (the page's own `.hero.model-hero`, first child of `<main>`)

Continues the pathway's teal. Content, top to bottom (CSS reorders the existing markup with
`order`; no markup change is needed):

1. `h1` (serif, white, `text-wrap: balance`): the page's one heading.
2. `.eyebrow`: **one subtitle line of key facts**, mono 13 px teal-100, in the tourism pattern
   ("Demand system · 2013 Q1 to 2025 Q1, 41 quarters"). For a model: `model id · country ·
   access (hosted/local) · horizon`. For a data page: `country · what it holds · latest vintage`.
   Written in lower case except proper nouns; no sentences.
3. `.lede`: **one or two sentences, ≤ 40 words**, in `rgba(255,255,255,.92)`. Phase 1 leaves the
   current ledes in place; phase 2 trims them and moves anything longer into an intro card
   (§4.10) below the sub-tabs.

On a model's four sub-pages (Methodology, Validation, Code, Paper) the title band shows the
model's title and subtitle only: **the lede appears on Overview alone** (each fact once). Phase 2
removes the repeated `.lede` from the sub-pages or replaces it with a tab-specific one-liner.

`/connect` uses `.connect-hero` (same band). The homepage hero is not a band: §7.1.

### 3.4 Section sub-tabs (second sticky row)

White strip under the header band (`top: var(--nav-h)`), hairline below, tabs 14 px Inter 500
`--text-muted`, 48 px high, left-aligned with the cards' content edge. Chosen tab =
`--surface-tint` fill + 3 px `--primary` underline + teal-700 600 text (fill and border; never a
tick). Hover = `--gray-100`. Scrolls sideways inside itself below the width it needs. Two markups
render identically:

| Markup | Where | Items | Source |
|---|---|---|---|
| `.model-tabs > .model-tabs-row > a.model-tabs-link[aria-current="page"]` | each model's 4 pages + its paper | Overview · Methodology · Validation · Code · Paper | `site_nav.SUBTABS` (written by `python3 site_nav.py --write`) |
| same, in-page anchors (`aria-current="location"` set by script) | `/models` | Models · Combine · Compare · Validation · Papers | `models/index.html` |
| same, in-page anchors | `/connect` | MCP · CLI · Python | `connect/index.html` |
| `.economy-subnav` (scope + topics) | `/forecasts`, `/forecasts/us`, `/economy`, `/economy/us`, 11 topic pages | **Forecasts** UK · US │ Overview · Data · Growth · Inflation · Jobs · Rates · Public finances · Reform | `economy/topics.py` between `forecasts-section-nav:begin/end` markers |
| `.model-tabs-set` buttons / `.glance-switch` | inside a card (view switches) | e.g. Validation views on `/models` | page HTML |

The model sub-tab rows are generated from one table in `site_nav.py` (`SUBTABS`, keyed by model
root; `SUBTAB_EXTRA` maps the DEFINE-UK replication report onto that model's Paper tab). Edit the
table, not the page, then run `python3 site_nav.py --write`. The rows stay outside `</header>`;
rows whose `aria-label` does not end in " pages" (`/models`, `/connect`) are hand-kept.

### 3.5 Footer (`.foot.foot-bar`)

**One row** on `--band-bg` (#133 removed the four-column directory on purpose; do not bring it
back): PolicyEngine (mark), GitHub, Contact, then the legal line. The views are the header tabs'
job, not the footer's (phase 1 briefly added Models, Forecasts and Use here; phase 2 reverted
that to match #133). It wraps to two lines on a phone. `site_nav.FOOTER_LINKS` is the only source; `economy/topics.py`
reads it. The body is a flex column so the footer sits at the viewport bottom on short pages.

### 3.6 Cache buster

`site_nav.STYLE_VERSION` (now 9). `render()` rewrites every page's stylesheet link to
`/style.css?v=N`; `economy/topics.py` and `notes/generate_release_notes.py` read
`site_nav.STYLE_HREF`. Bump the number in one place whenever a cached `style.css` would render a
page wrongly, then run `python3 site_nav.py --write`.

---

## 4. Components (CSS classes in `style.css`)

Markup is plain HTML. A component is a class contract: use the classes as written; do not add
page-local CSS that restyles them. "Legacy" names below are the classes the 110 pages already
use; they are restyled in place and stay valid.

### 4.1 Card: `section.band` (legacy) / `.card`

Every `section.band` is a white card: hairline border, `--radius-card`, `--shadow-card`,
`--card-pad` padding, `--gap-cards` between cards, max `--max` (1280 px) wide. `.band-alt`,
`.band-stack`, `.band-wide` are the same card (the old alternating tint is gone). `.band-result`
adds a 4 px `--primary` left rule: the one emphasised card per page (verdicts on `/`).
`.card` is the same surface for blocks inside a band; `.card-grid` lays cards out
auto-fit ≥ 260 px; `.card-flat` drops the shadow.

Card head = `.band-head` > `span.kicker.mono` (eyebrow, ≤ 4 words, no ordinal numbers in new
copy: "how far to trust it", not "03 — how far…") + `h2` (serif, ≤ 12 words) + optional
`p.section-intro` (**one sentence, ≤ 20 words**).

### 4.2 Stat tile (KPI): `.stat` (new) / `.metric` (legacy)

```html
<div class="stat-row">
  <div class="stat">
    <span class="stat-label"><span class="icon-badge" aria-hidden="true">…svg…</span>GDP fit, anchored</span>
    <span class="stat-value">0.30%</span>
    <span class="stat-sub">MAPE vs March 2026 EFO</span>
    <span class="stat-foot"><a class="chip" href="/obr/validation#caveats">By construction</a></span>
  </div>
</div>
```

Left 3 px accent (`.stat-us` = US blue, `.stat-neutral` = gray), label ≤ 5 words, value tabular
`--fs-stat` `--primary`, sub ≤ 6 words, foot for chips/links. A stat tile is the **home** of its
number (§1.1): put a tile only where the number lives. The legacy `.metrics > .metric` and
`.vmet-strip` render as tiles too.

### 4.3 Chip: `.chip` (new) / `.tag` (legacy)

Pill, 13 px, 26 px high (30 px when a link). Tones: default neutral, `.chip-brand`, `.chip-warn`,
`.chip-us`. Selected (`aria-pressed`/`aria-selected="true"`/`.is-selected`) = tint fill +
`--primary` border, weight 600, **no tick**. `.chip-row` wraps them. `.tag-hosted`,
`.tag-local`, `.tag-experimental`, `.tag-country` keep their colours on the pill shape. Chip text
≤ 5 words.

### 4.4 Callout: `.callout` (+ `.callout-warn`, `.callout-neutral`)

Tinted box, 1 px tinted border, 3 px left accent, `--radius`, 12/16 padding, 14 px text. Default
is info (teal tint). `.callout-warn` for caution (a failure statement may use it; it is not
red). `.callout-neutral` for asides ("It cannot …"). Lead with a bold phrase. Body ≤ 2 lines
(≈ 30 words) outside an expander; the existing long callouts are shortened in phase 2 with the
rest moved into an expander directly under them.

### 4.5 Expander: `details.expander` (and `details.about`)

Native `<details>`/`<summary>`: keyboard, find-in-page and no-JS all work. Summary 44 px target,
14 px 600 teal-700, rotating chevron drawn in CSS, optional `.expander-meta` right-aligned.
Body full card width, 14 px. Use one `details.about` per card at its foot for "About this"
(what it shows / how to read it / source / code), as in tourism §4 `About`; it explains and
links, never restates a number.

### 4.6 On this page rail: `.with-rail` + `nav.page-rail`

```html
<div class="with-rail">
  <nav class="page-rail" aria-label="On this page">
    <p class="page-rail-title">On this page</p>
    <a href="#trust" aria-current="location">How far to trust it</a> …
  </nav>
  <div> …section.band cards… </div>
</div>
```

From 1100 px: a sticky left column (200 px) with a 2 px rule per item, the item in view marked
by a `--primary` rule (`aria-current="location"`, set by the same IntersectionObserver idiom as
`economy/economy-nav.js`). Below 1100 px: a wrapping chip row above the cards. Use it on long
single-tab pages with ≥ 4 cards and no sub-tab row of in-page anchors: `/forecasts` (8
sections), each model's Validation tab, `/economy` and `/economy/us`. Never on a page whose
sub-tab row already lists the same anchors (`/models`, `/connect`). Every `href` must hit an id
that exists (the tests check).

### 4.7 Entry cards (AB): `.entry-grid > a.entry-card`

```html
<div class="entry-grid">
  <a class="entry-card" href="/models">
    <span class="icon-badge" aria-hidden="true">…svg…</span>
    <h3>Models</h3>
    <p>Seven models, and how far to trust each</p>
    <span class="entry-cta">Explore <span aria-hidden="true">→</span></span>
  </a>
</div>
```

3 px top rule, icon badge, title, one line ≤ 8 words, a filled "Explore →" pill. The whole card
is the link. For the homepage's three or four journeys and the hubs' "where next" rows.

### 4.8 Numbered steps: `ol.steps`

Numbered discs (CSS counter), title (`strong`) + one line (`span`, ≤ 12 words). 1 column on a
phone, auto-fit ≥ 220 px. For short "how it works" strips that do not need a figures panel
(e.g. the three MCP steps on `/connect`, the forecast lifecycle on `/forecasts`).

### 4.9 StepPanel (the two-sided explanation): `.scrolly-wrap`

The site's signature layout; keep it. Markup (already on 16 pages):

```html
<div class="scrolly-wrap">
  <div class="scrolly-steps">
    <div class="meth-step" id="pe-bridge" data-step="0">
      <div class="meth-step-head"><span class="meth-step-num mono">1</span><h3>With the microsimulation</h3></div>
      <p class="mo-lead">One sentence: what this step establishes.</p>
      … h4 sub-heads, prose, code, a figure …
      <div class="meth-inline"> …same figures as panel 0, shown < 900 px… </div>
    </div>
    …
  </div>
  <aside class="scrolly-sticky" aria-hidden="true">
    <div class="meth-panel" data-step="0">
      <div class="meth-panel-head"><span class="meth-panel-title">The bridge</span><span class="meth-panel-badge mono">Step 1</span></div>
      <div class="meth-sec-title">the join</div>
      <div class="meth-eq"><div class="meth-eq-label">entry point</div><div class="meth-eq-body">…</div></div>
    </div>
    <div class="meth-panel" data-step="1" hidden>…</div>
  </aside>
</div>
```

- Left: steps joined by a 2 px rail; the step at the reading line gets `.active` (the shared
  `/stepper.js`, loaded by every page with a `.scrolly-wrap` or a `.page-rail`; `site_nav.py`
  adds the tag and fails on an inline copy): the rail turns
  `--primary` and the number disc fills. **Inactive steps are not dimmed** (the old 28% opacity
  failed AA).
- Right (≥ 900 px): one white panel, 3 px teal top rule, `--shadow-raised`, sticky at
  `--sticky-top`, max height = viewport minus that (scrolls inside). Head = title + filled
  "Step n" pill. Body = `.meth-sec-title` (uppercase eyebrow with a trailing rule) and one
  `.meth-eq` per labelled figure (label + value, tabular, left-aligned; centred only for an
  equation).
- Below 900 px: the aside is hidden and each step shows its `.meth-inline` copy. Below 480 px
  the rail is dropped.
- The panel holds **only figures, labels and equations**: no prose paragraph, no number that is
  not also the subject of the step beside it. Each panel ≤ 6 `.meth-eq` rows.
- `.scrolly-code` on Code tabs: steps are code-length, not screen-length.

**Where it is used (required):** every model's Overview, Methodology and Code tab; each model's
Validation tab (OBR already; phase 2 converts the other six: svar, frb-us, us-hank, olg, pe,
define); the homepage "How the models connect" card (§7.1); `/models#compose` (Combine); the
`/connect` flow (MCP → CLI → Python, one step each, the panel showing the command for the chosen
route). Overview pages that are not StepPanels today (svar, frb-us, us-hank, olg, pe, define)
are converted in phase 2.

### 4.10 Intro card: `.intro-card`

AB pattern: a tinted card with a 4 px `--primary` left rule, placed directly under the sub-tab
row, holding the page's question in one sentence and at most two short paragraphs (the part of a
long lede that does not fit the title band), plus meta chips. One per page at most. The homepage
hero uses the same treatment (§7.1).

### 4.11 Buttons, icon badge, links

- `.btn.btn-primary` (filled teal, white) and `.btn.btn-secondary` / `.btn-ghost` (white,
  hairline, teal text), pill-shaped, 40 px min height. One primary per card.
- `.icon-badge`: 40 px tinted disc for an icon (28 px in stat labels).
- Links in text are underlined (WCAG 1.4.1), `--link`; external links open in the same tab
  unless they are downloads.
- Icons: 24 px grid, 1.75 stroke, round caps, `currentColor`, no fill, Lucide-style. The view
  icons are home, layers (Models), chart line (Forecasts), plug (Use). No check/tick icon exists
  in this set and none may be added.

---

## 5. Text budget (hard limits for new and rewritten copy)

| Element | Budget |
|---|---|
| Title-band subtitle (`.eyebrow`) | one line of facts, ≤ 70 characters, no verb |
| Title-band lede | ≤ 2 sentences, ≤ 40 words |
| Card eyebrow / title / lede | ≤ 4 words / ≤ 12 words / 1 sentence ≤ 20 words |
| Stat label / sub | ≤ 5 / ≤ 6 words |
| Chip | ≤ 5 words |
| StepPanel `.mo-lead` | 1 sentence ≤ 20 words |
| Panel `.meth-eq-label` / body | ≤ 3 words / ≤ 12 words |
| Chart caption | 1–2 lines, ≤ 30 words, says what is plotted and the source |
| Callout body | ≤ 2 lines outside an expander |
| Paragraph outside an expander | ≤ 4 lines at 1280 px; longer method text goes in an expander |

---

## 6. Chart house style (every generated SVG)

### 6.1 Rules

- Background: none (the card is the surface). One frame only: a chart inside a card does not
  get its own border (`.mo-figcard` / `.vfig` may add a hairline when two charts share a card).
- Grid: horizontal only, 1 px `--chart-grid`. Axis: 1.25 px `--chart-axis`. **Zero line**:
  1.25 px `--chart-zero`, drawn whenever the axis crosses zero.
- Ticks: mono 12 px rendered size, `--chart-tick`; first tick left-aligned, last right-aligned.
- Series (§6.2): our model / forecast solid 2.25 px; the official or published counterpart
  dashed 5 4, 2 px; at most two series plus neutrals; a third series only with a direct label.
- Fan / uncertainty: nested bands, outer to inner `--band-90` (13%), `--band-68` (26%), `--band-50`
  (38%) of `--primary`; median `--series-median` 2.5 px; realised data (outturn) as
  `--series-outturn` dots, never a line that could be read as a forecast.
- Legend: HTML under the chart (`.olg-legend` with `.ln-s1`, `.ln-s2` swatches) or direct
  labels at line ends; never a boxed SVG legend.
- Caption: `figcaption`, 13 px `--text-muted`: what is plotted, units, source, vintage.
- Every chart: `role="img"` + `aria-labelledby` pointing at a `<title>` and a `<desc>` that
  states the values a sighted reader would take away (the generators already do this; keep it).
- No colour encodes good/bad; no red/green.

### 6.2 Class → token map (generators emit the class; `style.css` §5.12 maps it)

| Class (emitted by) | Meaning | Token |
|---|---|---|
| `vc-grid`, `hf-grid` | gridline | `--chart-grid` |
| `vc-axis` | axis | `--chart-axis` |
| `vc-zero`, `hf-zero` | zero line | `--chart-zero` |
| `vc-tick`, `hf-tick`, `hf-q` | tick label | `--chart-tick`, mono |
| `vc-lab` | in-chart label | `--text-muted` |
| `vc-s1`, `vc-s1-dot`, `ln-s1` | our model / forecast | `--series-ours` |
| `vc-s2`, `vc-s2-dot`, `ln-s2` | official / published | `--series-official` (dashed) |
| `vc-s3` | third series (labelled) | gray 45% |
| `vc-band90`, `hf-b90` | 90% band | `--band-90` |
| `vc-band68`, `hf-b68` | 68% band | `--band-68` |
| `vc-band` | single band | primary 16% |
| `hf-med`, `hf-dot` | median path, end dot | `--series-median` |
| `vc-b1` / `vc-b2` / `vc-b3` | bar: result / comparison arms | primary / gray 55% / gray 35% |
| `vc-warn` | honest-warning cell/mark | `--warn-ink` |
| `vc-out-dot`, `vc-out-line` | realised data (outturn) | `--series-outturn` |
| `vc-ref`, `vc-edge`, `vc-outline` | reference rule, evidence edge, dashed outline | `--chart-axis` / `--text-strong` |
| `mm-*` | homepage model map | as above (pill stroke `--primary`, soft = dashed gray) |
| UK vs US on one chart (new: `vc-uk`, `vc-us`) | country | `--series-uk` / `--series-us` |

Model-family colours (`--family-micro`, `--family-structural`, `--family-empirical`,
`--family-ge`) are for chips and badges only, not chart series.

### 6.3 Readable labels: HTML over the SVG (`chartkit.py`, phase 3)

One approach, used by every generated chart (`validation/figures/make_charts.py`,
`forecasts/score.py`, `forecasts/make_open_fans.py`, `assets/make_hero.py`,
`assets/make_current_outlooks.py`, `economy/build.py`): **marks stay in the SVG, words move to
HTML.** A builder writes ordinary `<text>` at viewBox coordinates; `chartkit.figure()` lifts each
one into an absolutely positioned `<span class="vc-t …">` at the same point, in percent of the
viewBox, so it keeps its CSS size (12 px, `--fs-label`) at every width. Block contract:

```html
<div class="vc-fig" data-chart="ID">            container-type: inline-size
  <div class="vc-plot">
    <svg class="vchart" viewBox="…" preserveAspectRatio="none" role="img" aria-labelledby="ID-t ID-d">
      <title id="ID-t">…</title><desc id="ID-d">…</desc>   marks only, no <text>
    </svg>
    <div class="vc-labels" aria-hidden="true"><span class="vc-t vc-tick vc-y" style="left:…%;top:…%">…</span>…</div>
  </div>
  <ul class="vc-legend">…</ul>   <p class="vc-notes">…</p>
</div><!-- /vc-fig -->
```

- The viewBox is cropped to the plot area; axis labels hang outside it by fixed px offsets
  (`.vc-y`: 3 px above its gridline, inside the plot, left-aligned; `.vc-x`: 6 px under the axis;
  first x tick left-aligned, last right-aligned: `chartkit.ytick` / `chartkit.xtick`). No
  left gutter: it would be 25 px on a phone.
- The plot stretches to a usable height on a phone (`min-height` 210 px, per chart via
  `min_h`), so the SVG uses `preserveAspectRatio="none"`; strokes are non-scaling and dots are
  round-capped zero-length paths (chartkit converts `<circle>`), so nothing distorts.
- In-chart prose (`vc-note`) goes under the chart in `.vc-notes`; legends are `.vc-legend`
  swatches (`ln-s1` ours solid, `ln-s2` official dashed, `sw-b1…3` bars, `sw-band68/90`,
  `sw-dot-out` outturn, `sw-ring` hollow).
- Labels that cannot fit below 520 px of chart width carry `vc-minor` and are hidden by a
  container query; values a phone needs then come from `narrow_table=` (a small table shown
  only below 520 px: the panel/inline rule of §1.1, one of the two is visible).
- A chart that is really a table (`hank-targets`) is an HTML `table.vc-table` in a
  `.table-scroll`.
- The overlay is `aria-hidden`; `<title>`/`<desc>` carry the values for screen readers.
- The hero fan's value ticks sit in a gutter right of the plot (`.vc-gutter`), off the median,
  at every width; the year labels stay.
- Runtime charts (the OG-UK showcase, `olg/index.html`) draw at the container's pixel width
  (viewBox = rendered size) and redraw on resize, which gives the same 12 px labels.
- Every generator `--check` regenerates and compares, so the blocks cannot drift.

## 7. Per-page-type layout

### 7.0 Homes (each fact once)

| Fact | Home | Everywhere else |
|---|---|---|
| A model's validation numbers and verdict | that model's Validation tab | Overview: one verdict line + link; homepage and `/models`: verdict in words + link |
| A model's worked example (e.g. 1p on the basic rate) | that model's Overview, step "What it can answer" | homepage joins card: link only |
| Join mechanics (what moves, where it enters) | `/models#compose` | homepage: the join named + link; model Overview step 1: its own join only |
| Forecast rounds, bands, scores | `/forecasts#scored`, `#open`, `#rounds` | homepage proof card: link; topic pages: link |
| Latest data readings | the topic page (`/economy/topics/<topic>#stands`) | `/economy` list: the question + link (today it restates the reading: phase 3) |
| Data provenance (series, vintages) | `/forecasts#data` | topic `#data`: that series only |
| How to run (commands) | `/connect` (MCP, CLI, Python) | model Code tab: that model's own commands |
| Citations | the paper page | model pages link to it |

### 7.1 Home (`/`)

No title band. Header band → intro card (`.home-page .hero`: left accent, h1, one-sentence lede
naming the seven models with links, two buttons, the fan figure on the right ≥ 1000 px) →
**entry cards** (Models · Forecasts · Use, §4.7: one line each) → verdicts card
(`.band-result`: the three grades as words, each linking to a model's Validation tab; the scored
period as a link to `/forecasts#scored`, not a restated number) → "How the models connect" as a
**StepPanel** (step per join; the panel shows the pipeline and the join's entry point; the join
results link to their homes) → "Which model for which question" (the map, with the evidence lines
as links to each Validation tab) → start card (Connect button + client chips). Today's
`.vmet-notes` evidence lines and the join results repeat validation figures: phase 2 turns them
into links (§7.0).

### 7.2 Models hub (`/models`)

Title band (title, subtitle "7 models · UK and US · micro + macro") → sub-tabs Models · Combine ·
Compare · Validation · Papers (in-page anchors) → one card per anchor. Models = the question
list (each row: question, model chip, expand for the one-line verdict + "Open model →"). Combine =
StepPanel of the joins. Compare = the comparison table (`.table-scroll`). Validation = per-model
verdict rows linking to each Validation tab (no figures restated). Papers = paper cards linking to
`/papers/<id>`. At 375 the question rows stack the chip under the question (phase 2: today the
chip squeezes the question to one word per line).

### 7.3 A model (`/obr`, `/svar`, `/frb-us`, `/us-hank`, `/olg`, `/pe`, `/define`) and its tabs

Shell: title band (model title, subtitle `model id · country · hosted/local · horizon`) →
sub-tabs Overview · Methodology · Validation · Code · Paper. Every tab ends with a "where next"
row (entry cards or chips): the next tab, `/models#compare`, and `/connect` for hosted models.

| Tab | Layout | Must carry |
|---|---|---|
| Overview | lede (only here) → verdict callout (one line, `.callout-warn` if the verdict is a failure, links to Validation) → StepPanel: 1 With the microsimulation (the join), 2 What it is, 3 What it can answer (worked example = home) | link to the paper, `/models#compose`, Validation caveats |
| Methodology | StepPanel, one step per model block; panel = equations (`.meth-eq`) | the model's source paper citation (link to Paper tab) |
| Validation | stat row (the headline fit numbers: their home) → StepPanel of the tests (OBR is the reference) → limits card (`#caveats`, every failure statement in full) → "On this page" rail ≥ 1100 px | the verdict, every known limit, links to the code that produced each number |
| Code | `.scrolly-code` StepPanel: install → run → reproduce; panel = commands | `/connect` for hosted use, repo paths |
| Paper (`/papers/<id>`) | `.paper-viewer` card: title, meta line, Download PDF / All papers buttons, embedded PDF, abstract | status chip (draft/preprint/submitted/published), citation |

### 7.4 Papers and reports (`/papers/*`, `/reports/*`)

Same shell as their model (Models tab, model sub-tabs when the paper belongs to one model;
`/reports/us-hank-open-source` sits under `/us-hank`). One `.paper-viewer` card; reports are
long prose: cards per section + "On this page" rail.

### 7.5 Forecasts (`/forecasts`, `/forecasts/us`)

Title band (subtitle `UK · forecasts on the record · last round <date>`) → `.economy-subnav`
(Forecasts UK · US │ Overview · Data · topics) → "On this page" rail (run · status · scored ·
open · rounds · data · limits · notes) → cards. Status = stat row (rounds archived, periods
scored, next scoring date): the home of those counts. Scored = the dot plot per period
(forecast mark, band, outturn dot) with the verdict sentence. Open = fan charts. Rounds = the
archive table. Limits keeps every limit. US: same skeleton; "why there is no record" stays the
second card.

### 7.6 Economy data hubs and topic pages (`/economy`, `/economy/us`, `/economy/**/topics/*`)

Shell as Forecasts (they are Forecasts pages). Hub: topic list card (each row = the question +
topic chip + →; the reading lives on the topic page) → trends (three figures) → indicators,
markets, releases tables. Topic page: four cards in fixed order: Where it stands (stat row: home
of the readings) → What the models see (and what they cannot) → Run it yourself (command
block) → The data behind it (series, vintage file links). Generated by `economy/topics.py`.

### 7.7 Release notes (`/notes/releases/*`, `/notes/2026-07-25-cpi-2026q2`)

Forecasts tab chosen; pathway Home / Forecasts / Releases / <date>. Title band (series name;
subtitle `date · automated factual release note`; lede = the observation). Card 1 What changed
(one stat tile: the observation, its change; the tile is the only place the value appears),
card 2 Provenance (key/value `dl`, styled by `.band dl:not([class])`, plus publisher and snapshot
chips), then a "where next" row: the series' topic page, `/forecasts#data`, `/forecasts#rounds`.
No interpretation, ever (generator rule). Generated by `notes/generate_release_notes.py`; after a
template change run it with `--rebuild` (every committed note is rebuilt from its own snapshot),
and `--check` fails on any note that no longer matches the template.

### 7.8 Connect / Use (`/connect`)

Title band (`.connect-hero`) → sub-tabs MCP · CLI · Python → MCP card: client switch (segmented
chips, selected = fill), `ol.steps` (copy URL · add connector · ask), example prompts → CLI card
and Python card as a StepPanel (step = install / first command / reproduce; panel = the command
and its output shape) → "what each model can do hosted" table. Every model named links to its
page.

### 7.9 Contact (`/contact`)

Title band → one card: email button, "elsewhere" icon links (each with an `aria-label`). Nothing
else.

---

## 8. Flow and connections

The reading path the shell and the cross-links must support:

```
Home ──► Models hub ──► a model: Overview ─► Methodology ─► Validation ─► Code ─► Paper
  │           │                 │                              │
  │           └── Combine (joins) ◄─────────────── step 1 "with the microsimulation"
  │                                                            │
  ├──► Forecasts ─► scored / open / rounds ─► Data (vintages) ─► topic pages ─► release notes
  │                         ▲                                        │
  │                         └──── each forecast names its model ─────┘ (link to model Validation)
  └──► Use (/connect) ◄── every hosted model's Overview and Code tab
```

Required cross-links per page type (phase 2 adds what is missing; phase 4 checks):

| Page type | Must link to |
|---|---|
| Home | `/models`, `/forecasts`, `/connect`; each model page; each verdict's Validation tab; `/models#compose` |
| Models hub | every model Overview; every Validation tab (from the Validation card); every paper; `/connect` |
| Model Overview | its Methodology/Validation/Code/Paper (sub-tabs); `/pe` (the core) from the join step; `/models#compose`; `/connect` if hosted; any forecast it produces (`/forecasts#open`) |
| Model Validation | its Code tab (the code behind each number); `/models#validation`; its paper |
| Model Code | `/connect` (hosted route); the GitHub path |
| Forecasts | the model behind each forecast (Overview + Validation); `/forecasts#data`; topic pages; release notes |
| Data hub / topic | `/forecasts` (Overview tab); the model that forecasts the topic; vintage files; the series' release notes |
| Release note | its topic page; `/forecasts#data` |
| Connect | each model page; `/models` |

Every page ends with a "where next" row (2–4 chips or entry cards) naming the next step on this
path. The footer row is not a substitute for it.

---

## 9. Existing classes

- **Restyled in place, keep using:** `.band`, `.band-head`, `.kicker`, `.section-intro`, `.prose`,
  `.callout`, `.tag*`, `.metrics/.metric*`, `.btn*`, `.codeblock`, `.table-scroll`,
  `.model-tabs*`, `.economy-subnav*`, `.glance-switch`, `.scrolly-*`, `.meth-*`, `.vchart`,
  `.vc-*`, `.hf-*`, `.mm-*`, `.pipeline/.pl-*`, `.paper-viewer*`, `.crumbs`, `.foot*`.
- **New (phase 1, use for new work):** `.card`, `.card-grid`, `.stat-row/.stat*`, `.chip*`,
  `.icon-badge`, `details.expander`, `details.about`, `.with-rail/.page-rail`, `.entry-grid/.entry-card/.entry-cta`,
  `ol.steps`, `.intro-card`, `.callout-warn`, `.callout-neutral`.
- **Retired:** `.grain` (display: none; the `<div>` on every page is harmless, remove it when a
  page is touched), the fixed-header hero padding (each page's inline
  `.model-hero { padding-top: clamp(120px, 18vh, 180px) }` is now overridden by
  `.doc .hero.model-hero`; phase 2/3 delete those inline blocks from the pages and from
  `economy/topics.py`), inactive-step dimming.
- **Before removing any class, grep the pages and the generators for it** (`grep -rn
  'class-name' --include='*.html' --include='*.py' .`).

---

## 10. QA checklist (phase 4 runs this on every page type; screenshots at 1440 and 375)

- [ ] 375 px: `document.documentElement.scrollWidth == clientWidth` on every page (known open:
      `/forecasts` overflows by 51 px at 375 from the `#data` vintage-store block, pre-existing).
- [ ] Header band, title band, sub-tab row and footer present and identical in structure on all
      110 pages (`python3 site_nav.py` passes); the chosen view and sub-tab are marked by fill +
      underline, never a tick.
- [ ] Sticky rows: header stays at top, sub-tab row sticks directly under it, StepPanel panel
      and rail stick under both; an in-page anchor jump lands with its heading visible.
- [ ] Each fact once: grep the rendered text of each page type for its headline numbers (§7.0);
      a number outside its home is a defect unless it is the `.meth-panel`/`.meth-inline` pair.
- [ ] Every model's verdict and failure statements present (Overview line + Validation in full).
- [ ] No "poor"/"rich"; sentence case headings; neutral wording.
- [ ] No ✓/tick glyphs or icons.
- [ ] Contrast: no `--gray-400`/`--teal-300`/`--teal-500` text; text on bands only
      `--band-text`/`--band-text-dim`/white 92%.
- [ ] Focus ring visible on the header tabs, sub-tabs, chips, buttons, expanders, StepPanel
      links, including on the dark bands.
- [ ] Charts: `<title>`/`<desc>`; no SVG label renders below 11 px at 375 px; legend in HTML;
      zero line where the axis crosses zero; ours solid, official dashed.
- [ ] Text budget (§5).
- [ ] `pytest tests -q`, `python3 site_contract.py`, `python3 site_nav.py`, and the generators'
      `--check` modes (`economy/topics.py`, `economy/build.py`, `notes/generate_release_notes.py`)
      all pass.
- [ ] Dark theme (`prefers-color-scheme: dark`) renders every changed page legibly.

---

## 11. Phases

1. **Shell + tokens + this spec** (done): `style.css` token layer, shell, components and chart map;
   `site_nav.py` header/footer/cache buster; OBR Overview and Validation already use the StepPanel
   and are the reference for it.
2. **Model pages** (hand-written HTML: `/obr`, `/svar`, `/frb-us`, `/us-hank`, `/olg`, `/pe`,
   `/define` × 4 tabs, `/models`, `/`, `/connect`, `/contact`, papers, reports): apply §7 and §8,
   convert the remaining Overview/Validation pages to StepPanels, add verdict callouts, intro
   cards, stat rows, entry cards and "where next" rows, trim ledes and callouts to §5, remove
   duplicated figures per §7.0, delete inline hero padding blocks.
3. **Generators** (`economy/build.py`, `economy/topics.py`, `notes/generate_release_notes.py`,
   `forecasts/*.py`, `data/build_page.py`, `assets/make_hero.py`, `assets/make_current_outlooks.py`,
   `validation/figures/make_charts.py`): emit the §7.5–7.7 layouts, the §6 chart style, readable
   labels at 375, `SUBTABS` in `site_nav.py`, a shared `/stepper.js`, no restated readings on the
   hubs.
4. **QA**: §10 on every page type, both widths, both themes.
