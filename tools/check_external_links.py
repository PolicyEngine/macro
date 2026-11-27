"""Check every external link on the site. Network-dependent, so not a CI gate.

    python3 tools/check_external_links.py            # all pages
    python3 tools/check_external_links.py svar obr   # only these directories
    python3 tools/check_external_links.py --json out.json

The repo-root suite (tests/test_site_integrity.py) resolves internal links
against the filesystem. This script covers the other half: http(s) links to
other sites. It is a manual tool rather than a test because the result depends
on the network and on third-party servers, several of which refuse automated
clients, so a red run would not mean the site is broken.

Stdlib-only, like every other site script. Polite by design: one request per
host at a time, a pause between requests to the same host, HEAD first and a
ranged GET only when the server rejects HEAD.

Exit status is 1 when a link is definitely dead (404 or 410, or DNS failure).
A 401, 403, 429 or timeout is reported as "unverified", not as broken: many
publishers (ons.gov.uk, doi.org targets, bankofengland.co.uk) answer bots that
way for pages that load in a browser.
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {".git", "vendor", "node_modules", ".venv", "venv"}
USER_AGENT = "Mozilla/5.0 (compatible; site-link-check/1.0)"
TIMEOUT = 20
PAUSE_PER_HOST = 1.0
DEAD = {404, 410}
UNVERIFIED = {401, 403, 405, 406, 429, 500, 502, 503, 504, 999}
# Hosts that are placeholders or local examples in code samples, never links
# a reader is meant to follow.
SKIP_HOSTS = {"localhost", "127.0.0.1", "example.com", "www.w3.org"}


def _tls_context() -> ssl.SSLContext:
    """Default trust store, plus the system bundle a python.org macOS build
    does not load on its own. Without it every HTTPS link reads as unverified."""
    context = ssl.create_default_context()
    for bundle in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt"):
        if Path(bundle).exists():
            context.load_verify_locations(bundle)
            break
    return context


TLS = _tls_context()


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[tuple[str, int]] = []

    def handle_starttag(self, tag, attrs):
        if tag not in ("a", "link", "script", "img", "iframe"):
            return
        attrs = dict(attrs)
        if tag == "link" and attrs.get("rel") in ("canonical", "preconnect", "dns-prefetch"):
            return
        url = attrs.get("href") or attrs.get("src") or ""
        if url.startswith(("http://", "https://")):
            self.found.append((url, self.getpos()[0]))


def collect(only: list[str]) -> dict[str, list[str]]:
    """Map each external URL (fragment removed) to the places that cite it."""
    cited: dict[str, list[str]] = defaultdict(list)
    for path in sorted(ROOT.rglob("*.html")):
        rel = path.relative_to(ROOT)
        if EXCLUDED_DIRS & set(rel.parts):
            continue
        if only and rel.parts[0] not in only:
            continue
        parser = _Links()
        parser.feed(path.read_text(encoding="utf-8"))
        for url, line in parser.found:
            url = urldefrag(url)[0]
            if urlsplit(url).hostname in SKIP_HOSTS:
                continue
            cited[url].append(f"{rel}:{line}")
    return cited


def _request(url: str, method: str) -> int:
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if method == "GET":
        headers["Range"] = "bytes=0-2047"
    request = urllib.request.Request(url, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT, context=TLS) as response:
        return response.status


def probe(url: str) -> tuple[str, str]:
    """Return (verdict, detail). Verdict is ok, dead or unverified."""
    last = ""
    for method in ("HEAD", "GET"):
        try:
            status = _request(url, method)
            return "ok", str(status)
        except urllib.error.HTTPError as error:
            last = str(error.code)
            if error.code in DEAD and method == "GET":
                return "dead", last
            if error.code in DEAD or error.code in UNVERIFIED:
                continue
            return "unverified", last
        except urllib.error.URLError as error:
            reason = error.reason
            if isinstance(reason, socket.gaierror):
                return "dead", f"DNS: {reason}"
            last = f"{type(reason).__name__}: {reason}"
        except (TimeoutError, ssl.SSLError, ConnectionError, OSError) as error:
            last = f"{type(error).__name__}: {error}"
    return ("dead" if last in {str(code) for code in DEAD} else "unverified"), last


def check_host(urls: list[str]) -> dict[str, tuple[str, str]]:
    results = {}
    for index, url in enumerate(urls):
        if index:
            time.sleep(PAUSE_PER_HOST)
        results[url] = probe(url)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("only", nargs="*", help="top-level directories to scan")
    parser.add_argument("--json", metavar="PATH", help="also write results as JSON")
    args = parser.parse_args()

    cited = collect(args.only)
    by_host: dict[str, list[str]] = defaultdict(list)
    for url in cited:
        by_host[urlsplit(url).hostname or ""].append(url)

    results: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        for chunk in pool.map(check_host, by_host.values()):
            results.update(chunk)

    counts = defaultdict(int)
    for verdict, _ in results.values():
        counts[verdict] += 1
    for verdict in ("dead", "unverified"):
        for url in sorted(u for u, (v, _) in results.items() if v == verdict):
            print(f"{verdict.upper():10} {results[url][1]:>6}  {url}")
            for place in cited[url][:5]:
                print(f"{'':19}{place}")
            if len(cited[url]) > 5:
                print(f"{'':19}... and {len(cited[url]) - 5} more")
    print(
        f"{len(results)} external URLs on {len(by_host)} hosts: "
        f"{counts['ok']} ok, {counts['unverified']} unverified, {counts['dead']} dead"
    )
    if args.json:
        Path(args.json).write_text(
            json.dumps(
                {u: {"verdict": v, "detail": d, "cited": cited[u]} for u, (v, d) in sorted(results.items())},
                indent=2,
            )
        )
    return 1 if counts["dead"] else 0


if __name__ == "__main__":
    sys.exit(main())
