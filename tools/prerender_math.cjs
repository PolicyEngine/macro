// Render TeX to MathJax CHTML at authoring time (called by prerender_math.py).
// stdin:  {"items": [{"tex": "...", "display": false}, ...], "scale": 1.236}
// stdout: {"version": "3.2.2", "items": ["<mjx-container ...>", ...], "css": "..."}
// Needs mathjax-full 3.2.2 (tools/package.json); MATHJAX_FULL may point at
// another node_modules/mathjax-full checkout.
"use strict";
const path = require("path");
const base = process.env.MATHJAX_FULL || path.join(__dirname, "node_modules", "mathjax-full");
const req = (p) => require(path.join(base, "js", p));
const { mathjax } = req("mathjax.js");
const { TeX } = req("input/tex.js");
const { CHTML } = req("output/chtml.js");
const { liteAdaptor } = req("adaptors/liteAdaptor.js");
const { RegisterHTMLHandler } = req("handlers/html.js");
const { AssistiveMmlHandler } = req("a11y/assistive-mml.js");
const { AllPackages } = req("input/tex/AllPackages.js");
const { VERSION } = req("components/version.js");

const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const adaptor = liteAdaptor();
AssistiveMmlHandler(RegisterHTMLHandler(adaptor));
const tex = new TeX({ packages: AllPackages });
const chtml = new CHTML({ fontURL: "/vendor/mathjax/output/chtml/fonts/woff-v2" });
const doc = mathjax.document("", { InputJax: tex, OutputJax: chtml });
// The page sets equations in Inter, whose x-height is what the browser
// runtime measured (font-size 123.6%); fix it here so every page matches.
const em = 16, ex = em * 0.442 * input.scale;
const items = input.items.map((it) =>
  adaptor.outerHTML(doc.convert(it.tex, { display: !!it.display, em, ex, containerWidth: 80 * em, scale: input.scale }))
);
const css = adaptor.textContent(chtml.styleSheet(doc));
process.stdout.write(JSON.stringify({ version: VERSION, items, css }));
