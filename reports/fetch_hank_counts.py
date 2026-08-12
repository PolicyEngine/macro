#!/usr/bin/env python3
"""Refresh the citation and star counts in reports/us-hank-open-source.html.

The report said its counts "use canonical OpenAlex records" and the GitHub
API, but nothing recorded when they were taken and no script existed to
retake them, so a reader had no way to tell a current number from a stale
one. Two had drifted by the time this was written (Kaplan-Moll-Violante
1,359 -> 1,377; Sequence-Space Jacobian 245 -> 248).

Counts move every day. The point of this script is not to keep them exact
-- it is that the page carries a retrieval date and anyone can reproduce
the numbers under it.

    python3 reports/fetch_hank_counts.py           # print what is live now
    python3 reports/fetch_hank_counts.py --check   # exit 1 if the page drifts
                                                   # by more than the tolerance

Network-dependent, so this is deliberately NOT wired into CI: a citation
count is not a build-breaking fact, and a flaky external API should not
fail a site build.
"""

from __future__ import annotations

import argparse
import json
import re
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

PAGE = Path(__file__).resolve().parent / "us-hank-open-source.html"

# label -> (OpenAlex work id, GitHub repo or None, substring that identifies
# the row in the page). The row marker is the paper title rather than the
# short name because the table prints names with en-dashes and diacritics
# ("Bayer-Born-Lutticke"), which an ASCII key does not match.
SOURCES = {
    "Bayer-Born-Lutticke": (
        "W3121400794", "FRBNY-DSGE/HANK_BusinessCycleAndInequality",
        "Shocks, Frictions, and Inequality"),
    "FRBNY Estimating HANK": (
        "W4386056217", "FRBNY-DSGE/Estimating_HANK",
        "Central-bank estimation and forecast evaluation"),
    "Kaplan-Moll-Violante": (
        "W2253894436", None, "Monetary Policy According to HANK"),
    "Sequence-Space Jacobian": (
        "W2964550494", "shade-econ/sequence-jacobian",
        "One- and two-asset HANK examples"),
    "Fed Board HANK Comes of Age": (
        "W7124136732", None, "heterogeneous overlapping generations"),
}

# A citation count that has moved by a few is not a defect in the page; one
# that has moved by a fifth means the table is describing a different world.
DRIFT_TOLERANCE = 0.10


def _get(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": "policyengine-macro-report-check"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.URLError as error:
        # urllib wraps the certificate error in URLError, so catching
        # SSLCertVerificationError directly never fires.
        if not isinstance(getattr(error, "reason", None), ssl.SSLCertVerificationError):
            raise
        # A python.org framework build ships without a CA bundle unless
        # "Install Certificates.command" was run, so urllib cannot verify
        # anything while curl on the same machine can. Falling back keeps this
        # script usable there without adding a certifi dependency to a
        # deliberately stdlib-only tree.
        completed = subprocess.run(
            ["curl", "-sS", "--fail", "-H",
             "User-Agent: policyengine-macro-report-check", url],
            capture_output=True, text=True, timeout=30,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"both urllib (TLS verification) and curl failed for {url}: "
                f"{completed.stderr.strip()}"
            ) from None
        return json.loads(completed.stdout)


def live() -> dict[str, dict]:
    out = {}
    for label, (work, repo, _row) in SOURCES.items():
        record = {"citations": _get(f"https://api.openalex.org/works/{work}")["cited_by_count"]}
        if repo:
            record["stars"] = _get(f"https://api.github.com/repos/{repo}")["stargazers_count"]
        out[label] = record
    return out


def published() -> dict[str, int]:
    """Citation counts as the page currently prints them, keyed by label."""
    html = PAGE.read_text()
    out = {}
    for label, (_work, _repo, row_marker) in SOURCES.items():
        # Year then Citations are the first two numeric cells after the row's
        # title text.
        pattern = (
            rf"{re.escape(row_marker)}.*?"
            rf'<td class="num">[^<]*</td><td class="num">([\d,]+)'
        )
        found = re.search(pattern, html, re.DOTALL)
        if not found:
            # A checker that silently skips a row it cannot find is the same
            # failure this script exists to prevent.
            raise SystemExit(
                f"cannot find the {label} row in {PAGE.name} via "
                f"{row_marker!r}; the table changed and this script must be "
                "updated with it"
            )
        out[label] = int(found.group(1).replace(",", ""))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if a published count has drifted materially")
    args = parser.parse_args()

    current = live()
    for label, record in current.items():
        stars = record.get("stars")
        print(f"{label:32s} citations={record['citations']:>6,}"
              + (f"  stars={stars}" if stars is not None else ""))

    if not args.check:
        return 0

    stale = []
    for label, count in published().items():
        now = current[label]["citations"]
        if count == 0 or now == 0:
            continue
        if abs(now - count) / max(now, count) > DRIFT_TOLERANCE:
            stale.append(f"{label}: page says {count:,}, OpenAlex says {now:,}")
    if stale:
        print("\nDRIFT — rerun without --check and update the table and its date:",
              *stale, sep="\n  ")
        return 1
    print("\nOK — published counts are within "
          f"{DRIFT_TOLERANCE:.0%} of the live records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
