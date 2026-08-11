# Security policy

## Reporting a vulnerability

Report security issues privately through GitHub's
[private vulnerability reporting](https://github.com/PolicyEngine/macro/security/advisories/new)
on this repository. Please do not open a public issue for anything exploitable.

Include what you did, what happened, and what you expected — a reproduction is
worth more than a description. We aim to acknowledge within three working days.

## What is in scope

This repository contains three separable things, and they carry different risks:

| surface | what an issue here would look like |
|---------|-----------------------------------|
| **Hosted MCP server** (`integration/modal_app.py`, deployed to Modal) | unauthenticated resource exhaustion, input that escapes the model sandbox, tool inputs that reach a shell or filesystem, responses leaking server state |
| **`policyengine-macro` package** (`integration/`) | code execution through crafted reform/parameter input, unsafe deserialisation, dependency confusion in the `[models]` extra |
| **The static site** | injection through committed generated HTML, a Content-Security-Policy or header regression in `vercel.json` |

The hosted MCP server is public and unauthenticated by design: it runs
serverless, scales to zero, and executes only the fixed tool surface asserted by
`integration/tests/test_tool_surface.py`. Reports that it can be called by
anyone are not vulnerabilities. Reports that a call can make it do something
outside that tool surface are.

## What is out of scope

- **Model results being wrong or disputed.** That is a correctness or
  methodology question, not a security one — open a normal issue. Every model
  here states its limits in `integration/src/policyengine_macro/capabilities.py`,
  including what it explicitly cannot answer.
- **The upstream model repositories.** Report those to the repository that owns
  the code: `obr-macroeconomic-model`, `boe-var-model`, `us-frb-model`,
  `us-hank-model`, `PSLmodels/OG-UK`, `policyengine.py`.
- **Missing rate limits on public official-statistics endpoints** that
  `data/fetch.py` reads (ONS, Bank of England, FRED).

## Data integrity is a security property here

Two stores in this repository are append-only, and that immutability is the
whole basis of claims the site makes publicly:

- `data/vintages/**` — dated snapshots of official statistics. If a snapshot
  could be silently edited, look-ahead bias would become undetectable and no
  published number could be reproduced.
- `forecasts/rounds/**` — archived forecast rounds. A forecast track record is
  only evidence if a round provably existed before its outturn did.

Both are enforced in CI (`.github/workflows/data-immutability.yml` and
`forecast-archive.yml`). **A way to modify or delete history in either store
without CI failing is a valid security report**, even though nothing is
"hacked" in the conventional sense. Please report it as one.

## Supply chain

The `[models]` extra in `integration/pyproject.toml` pins every model
dependency to a full 40-character commit SHA rather than a branch or tag, so an
upstream force-push cannot silently change what gets installed. That pinning is
asserted by `tests/test_repo_hygiene.py`. If you find a path by which a
dependency resolves to something other than its pinned SHA, that is in scope.
