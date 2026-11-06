"""Drift check: do the hosted models still return the numbers the site quotes?

Each canary in ``canaries.json`` is one cheap call to one hosted model whose
output a page quotes, with the expected value, a tolerance and the page that
quotes it (the line is found from ``quoted_anchor``, so edits higher up the
page do not stale the pointer). The check calls the hosted MCP server (the same streamable-HTTP
client as ``tests/test_remote_mcp.py``) and fails with a diff when

- a quoted value has moved outside its tolerance (``value``),
- the hosted provenance names a model id or source URL that is not the
  capability registry's (``provenance``), or
- the hosted source revision is not the revision ``modal_app.py`` pins
  (``revision``): the deployment is stale against the committed pin.

Why this exists: the hosted ``score_reform(model="obr")`` returned GDP +£5.6bn
for a tax rise on a stale OBR pin while the site quoted the correct numbers,
and nothing caught it (macro #218, #226).

Usage (from ``integration/``)::

    python drift/drift_check.py                     # hosted, all canaries
    python drift/drift_check.py --only obr_bank_rate_q12
    python drift/drift_check.py --save-raw raw.json # keep raw responses
    python drift/drift_check.py --from-raw raw.json # re-evaluate offline
    python drift/drift_check.py --local             # also run the locally
                                                    # pinned packages where
                                                    # the canary is cheap

Exit status: 0 all pass, 1 drift found, 2 the check itself could not run.
Needs only ``mcp`` for hosted calls; the registry and pins are read from
source files, so the full model stack is not imported unless ``--local``.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
INTEGRATION = HERE.parent
CANARIES = HERE / "canaries.json"
DEFAULT_URL = "https://policyengine--policyengine-macro-mcp-serve.modal.run/mcp"
# modal_app.py pin name for each registry id that records a source revision.
PIN_FOR_MODEL = {
    "obr-macro": "OBR_REVISION",
    "boe-svar": "BOE_REVISION",
    "frb-us": "FRB_REVISION",
    "us-hank": "HANK_REVISION",
}


# --- registry and pins (read from source, no heavy imports) ----------------


def load_registry() -> dict:
    """The capability registry's MODELS dict (capabilities.py imports only copy)."""
    path = INTEGRATION / "src" / "policyengine_macro" / "capabilities.py"
    spec = importlib.util.spec_from_file_location("_pem_capabilities", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.MODELS


def load_pins() -> dict[str, str]:
    """The *_REVISION constants modal_app.py deploys."""
    tree = ast.parse((INTEGRATION / "modal_app.py").read_text())
    pins = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in PIN_FOR_MODEL.values()
            and isinstance(node.value, ast.Constant)
        ):
            pins[node.targets[0].id] = node.value.value
    return pins


def load_canaries(path: Path = CANARIES) -> list[dict]:
    return json.loads(path.read_text())["canaries"]


# --- extraction and comparison (pure; unit-tested) --------------------------


def extract(obj, spec: dict):
    """Pull one number out of a tool response.

    ``spec["path"]`` is a list of keys/indices; ``"*"`` maps over a list. A
    ``{"key": k, "equals": v}`` element selects the first list item whose
    ``k`` equals ``v`` (e.g. a quarter label). After the path, an optional
    ``reduce`` (min, max, first, last, mean, sum) collapses a list, then the
    value is multiplied by ``scale`` (default 1).
    """
    cur = [obj]
    mapped = False
    for step in spec["path"]:
        nxt = []
        for item in cur:
            if step == "*":
                if not isinstance(item, list):
                    raise KeyError(f"'*' applied to {type(item).__name__}")
                nxt.extend(item)
                mapped = True
            elif isinstance(step, dict):
                hits = [x for x in item if isinstance(x, dict)
                        and x.get(step["key"]) == step["equals"]]
                if not hits:
                    raise KeyError(f"no item with {step['key']}={step['equals']!r}")
                nxt.append(hits[0])
            elif isinstance(step, int):
                nxt.append(item[step])
            else:
                if not isinstance(item, dict) or step not in item:
                    raise KeyError(f"missing key {step!r}")
                nxt.append(item[step])
        cur = nxt
    value = cur if mapped else cur[0]
    reducer = spec.get("reduce")
    if reducer:
        if not isinstance(value, list):
            value = [value]
        vals = [float(v) for v in value]
        value = {
            "min": min, "max": max, "sum": sum,
            "first": lambda v: v[0], "last": lambda v: v[-1],
            "mean": lambda v: sum(v) / len(v),
        }[reducer](vals)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if spec.get("equals") is not None:
            return value
        raise TypeError(f"extracted {value!r}, not a number")
    return float(value) * float(spec.get("scale", 1.0))


def compare_value(observed, expected, tolerance: float) -> tuple[bool, str]:
    """Absolute-tolerance comparison with a printable diff."""
    if isinstance(expected, (bool, str)) or observed is None:
        ok = observed == expected
        return ok, "" if ok else f"got {observed!r}, expected {expected!r}"
    if not isinstance(observed, (int, float)) or not math.isfinite(observed):
        return False, f"got non-finite {observed!r}"
    diff = observed - expected
    ok = abs(diff) <= tolerance
    return ok, "" if ok else (
        f"got {observed:.4g}, expected {expected:.4g} ± {tolerance:g} "
        f"(off by {diff:+.4g})"
    )


def find_provenance(response) -> dict | None:
    """The response's provenance block, wherever the adapter put it."""
    if not isinstance(response, dict):
        return None
    if isinstance(response.get("provenance"), dict):
        return response["provenance"]
    score = response.get("score")
    if isinstance(score, dict) and isinstance(score.get("provenance"), dict):
        return score["provenance"]
    return None


def check_provenance(canary: dict, response, registry: dict,
                     pins: dict[str, str]) -> list[tuple[str, str]]:
    """(kind, message) failures for model id, source URL and revision."""
    if not canary.get("check_provenance", True):
        return []
    prov = find_provenance(response)
    if prov is None:
        return [("provenance", "response carries no provenance block")]
    out = []
    want_id = canary["model_id"]
    got_id = prov.get("model_id")
    if got_id != want_id:
        out.append(("provenance",
                    f"model_id {got_id!r}, registry id is {want_id!r}"))
    want_url = registry.get(want_id, {}).get("source_url")
    got_url = prov.get("source_url")
    if want_url and got_url != want_url:
        out.append(("provenance",
                    f"source_url {got_url!r}, registry says {want_url!r}"))
    pin_name = PIN_FOR_MODEL.get(want_id)
    if pin_name and pin_name in pins:
        got_rev = prov.get("source_revision")
        if got_rev != pins[pin_name]:
            out.append(("revision",
                        f"hosted revision {got_rev!r}, modal_app.py "
                        f"{pin_name} is {pins[pin_name][:12]} (redeploy?)"))
    return out


def quoted_location(canary: dict) -> str:
    """``path:line`` of the quote, found by its anchor on the page today.

    ``quoted_at`` names the page only; a stored line number went stale every
    time a stacked PR edited the page above the quote. Falls back to the page
    when there is no anchor or it is not found (the tests require it once).
    """
    path = canary["quoted_at"].split(":", 1)[0]
    anchor = canary.get("quoted_anchor")
    if anchor:
        try:
            lines = (INTEGRATION.parent / path).read_text().splitlines()
        except OSError:
            return path
        for i, text in enumerate(lines, 1):
            if anchor in text:
                return f"{path}:{i}"
    return path


def evaluate(canary: dict, response, registry: dict, pins: dict[str, str],
             source: str = "hosted") -> dict:
    """One result row: status pass/fail/error, observed values, failures."""
    row = {"id": canary["id"], "source": source, "tool": canary["tool"],
           "quoted_at": quoted_location(canary), "failures": [], "observed": {}}
    if isinstance(response, dict) and "__error__" in response:
        row["status"] = "error"
        row["failures"].append(("error", response["__error__"]))
        return row
    checks = canary["checks"]
    if source == "local" and canary.get("local_checks"):
        # e.g. DEFINE-UK: hosted only refuses, the cached local run has numbers
        checks = canary["local_checks"]
    for chk in checks:
        try:
            got = extract(response, chk)
        except (KeyError, IndexError, TypeError, ValueError) as e:
            row["failures"].append(("value", f"{chk['name']}: cannot extract ({e})"))
            continue
        row["observed"][chk["name"]] = got
        ok, msg = compare_value(got, chk["expected"], chk.get("tolerance", 0.0))
        if not ok:
            row["failures"].append(("value", f"{chk['name']}: {msg}"))
    if source == "hosted":
        row["failures"].extend(check_provenance(canary, response, registry, pins))
    row["status"] = "fail" if row["failures"] else "pass"
    return row


def skipped_row(canary: dict, why: str) -> dict:
    """A local row that could not run here; reported, never counted as drift."""
    return {"id": canary["id"], "source": "local", "tool": canary["tool"],
            "quoted_at": quoted_location(canary), "status": "skipped",
            "failures": [], "observed": {"skipped": why}}


def validate_canaries(canaries: list[dict], registry: dict) -> list[str]:
    """Static problems with the canary list itself (used by the tests)."""
    problems, seen = [], set()
    for c in canaries:
        cid = c.get("id", "?")
        if cid in seen:
            problems.append(f"{cid}: duplicate id")
        seen.add(cid)
        for key in ("model_id", "source_url", "tool", "args", "quoted_at",
                    "quote", "checks", "cost"):
            if key not in c:
                problems.append(f"{cid}: missing {key}")
        mid = c.get("model_id")
        if mid not in registry:
            problems.append(f"{cid}: model_id {mid!r} is not a registry id")
        elif c.get("source_url") != registry[mid].get("source_url"):
            problems.append(f"{cid}: source_url differs from the registry")
        if c.get("cost") not in ("cheap", "moderate"):
            problems.append(f"{cid}: cost must be cheap or moderate")
        for chk in c.get("checks", []) + c.get("local_checks", []):
            if "name" not in chk or "path" not in chk or "expected" not in chk:
                problems.append(f"{cid}: check needs name, path, expected")
            tol = chk.get("tolerance", 0.0)
            if not isinstance(tol, (int, float)) or tol < 0:
                problems.append(f"{cid}: bad tolerance {tol!r}")
    return problems


def render(rows: list[dict]) -> str:
    """Markdown report: a table, then every failure verbatim."""
    lines = ["| canary | source | status | observed | quoted at |",
             "|---|---|---|---|---|"]
    for r in rows:
        obs = ", ".join(f"{k}={v:.6g}" if isinstance(v, float) else f"{k}={v}"
                        for k, v in r["observed"].items()) or "—"
        lines.append(f"| `{r['id']}` | {r['source']} | **{r['status']}** | "
                     f"{obs} | `{r['quoted_at']}` |")
    bad = [r for r in rows if r["failures"]]
    if bad:
        lines += ["", "### Diffs", ""]
        for r in bad:
            for kind, msg in r["failures"]:
                lines.append(f"- `{r['id']}` ({r['source']}, {kind}): {msg}")
    return "\n".join(lines)


# --- callers ----------------------------------------------------------------


async def _hosted_calls(url: str, canaries: list[dict], timeout: float,
                        job_deadline: float = 600.0) -> dict:
    """One MCP session per canary, mirroring tests/test_remote_mcp.py::_call.

    A failed call is recorded, not raised, so one broken tool does not hide
    the rest. Calls run one after another: max_containers=3 on Modal and
    there is no reason to fan out.
    """
    import asyncio

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async def call(tool, arguments):
        async with streamablehttp_client(url, timeout=timeout) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool(tool, arguments)
                text = "\n".join(x.text for x in res.content
                                 if getattr(x, "text", None))
                if res.isError:
                    return {"__error__": f"{tool} error: {text[:500]}"}
                return json.loads(text)

    async def via_job(c):
        """start_job + short get_job_result polls: the path for any call that
        can pass Modal's 150s HTTP ceiling on a cold container."""
        job = await call("start_job", {"tool": c["tool"], "arguments": c["args"]})
        if "__error__" in job:
            return job
        deadline = time.time() + job_deadline
        while time.time() < deadline:
            try:
                r = await call("get_job_result",
                               {"job_id": job["job_id"], "wait_seconds": 30})
            except Exception:  # noqa: BLE001 - a failed poll is not a failed job
                await asyncio.sleep(5)  # no tight reconnect loop against Modal
                continue
            if "__error__" in r or r.get("status") == "done":
                return r.get("result", r)
        return {"__error__": f"job {job['job_id']} not done after {job_deadline:.0f}s"}

    out = {}
    for c in canaries:
        t0 = time.time()
        try:
            if c.get("via_job"):
                out[c["id"]] = await via_job(c)
            else:
                out[c["id"]] = await asyncio.wait_for(
                    call(c["tool"], c["args"]), timeout=timeout + 30)
        except Exception as e:  # noqa: BLE001 - record and continue
            out[c["id"]] = {"__error__": f"{type(e).__name__}: {e}"[:500]}
        print(f"  {c['id']}: {time.time() - t0:.1f}s", file=sys.stderr, flush=True)
    return out


def _local_call(canary: dict):
    """Run the canary against the locally installed, pinned packages."""
    sys.path.insert(0, str(INTEGRATION / "src"))
    from policyengine_macro import mcp_server

    fn = getattr(mcp_server, canary["tool"])
    fn = getattr(fn, "fn", fn)  # FastMCP may wrap the function
    return fn(**canary["args"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default=os.environ.get(
        "POLICYENGINE_MACRO_REMOTE_URL", DEFAULT_URL))
    ap.add_argument("--only", action="append", default=[],
                    help="canary id to run (repeatable)")
    ap.add_argument("--max-cost", choices=("cheap", "moderate"),
                    default="moderate")
    ap.add_argument("--local", action="store_true",
                    help="also run canaries marked local_cheap on the "
                         "locally pinned packages")
    ap.add_argument("--save-raw", type=Path)
    ap.add_argument("--from-raw", type=Path,
                    help="re-evaluate saved hosted responses; no network")
    ap.add_argument("--report", type=Path, help="write the markdown report here")
    ap.add_argument("--timeout", type=float, default=140.0,
                    help="per-call seconds (Modal drops HTTP requests at 150s)")
    args = ap.parse_args(argv)

    try:
        registry, pins = load_registry(), load_pins()
        canaries = load_canaries()
    except Exception as e:  # noqa: BLE001
        print(f"drift check could not load its inputs: {e}", file=sys.stderr)
        return 2
    problems = validate_canaries(canaries, registry)
    if problems:
        print("canary list is invalid:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    if args.only:
        canaries = [c for c in canaries if c["id"] in args.only]
    if args.max_cost == "cheap":
        canaries = [c for c in canaries if c["cost"] == "cheap"]

    if args.from_raw:
        raw = json.loads(args.from_raw.read_text())
    else:
        import anyio

        raw = anyio.run(_hosted_calls, args.url, canaries, args.timeout)
    if args.save_raw:
        args.save_raw.write_text(json.dumps(raw, indent=1, default=str) + "\n")

    rows = [evaluate(c, raw.get(c["id"], {"__error__": "not called"}),
                     registry, pins) for c in canaries]
    if args.local:
        for c in canaries:
            if not c.get("local_cheap"):
                continue
            try:
                resp = _local_call(c)
            except ModuleNotFoundError as e:
                rows.append(skipped_row(c, f"model package not installed ({e.name})"))
                continue
            except Exception as e:  # noqa: BLE001
                resp = {"__error__": f"local: {type(e).__name__}: {e}"[:500]}
            rows.append(evaluate(c, resp, registry, pins, source="local"))

    report = render(rows)
    print(report)
    if args.report:
        args.report.write_text(report + "\n")
    return 1 if any(r["status"] in ("fail", "error") for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
