"""The methodology pages' equations are pre-rendered MathJax CHTML.

tools/prerender_math.py typesets the TeX at authoring time so the pages load
no MathJax runtime (it was 1.3 MB). These tests keep the output tied to its
TeX source: the node-free checks run everywhere; the full re-render runs when
node and mathjax-full are installed (``npm ci --prefix tools``).
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("prerender_math", ROOT / "tools" / "prerender_math.py")
prerender = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prerender)


def test_equations_match_their_tex_and_no_raw_tex_is_left():
    assert prerender.verify_static() == []


def test_every_page_with_tex_is_in_the_prerender_list():
    tracked = subprocess.run(
        ["git", "ls-files", "*.html"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    with_math = {
        ROOT / f for f in tracked if prerender.find_math((ROOT / f).read_text())
    }
    assert with_math <= set(prerender.PAGES)


def test_no_page_or_script_loads_the_mathjax_runtime():
    assert not (ROOT / "vendor" / "mathjax" / "tex-chtml-full.js").exists()
    for path in [ROOT / "stepper.js", *prerender.PAGES]:
        assert "tex-chtml" not in path.read_text(), path


def test_an_edited_equation_is_caught(tmp_path):
    page = prerender.PAGES[0]
    text = page.read_text()
    tex = re.search(r'data-tex="([^"]+)"', text).group(1)
    edited = tmp_path / page.name
    edited.write_text(text.replace(f'data-tex="{tex}"', f'data-tex="{tex}+1"', 1))
    prerender.ROOT = tmp_path  # relative_to() in messages
    try:
        assert any("edited without re-rendering" in p for p in prerender.verify_static([edited]))
    finally:
        prerender.ROOT = ROOT


def _mathjax_available() -> bool:
    node = os.environ.get("NODE") or shutil.which("node")
    mj = os.environ.get("MATHJAX_FULL") or str(ROOT / "tools" / "node_modules" / "mathjax-full")
    return bool(node) and Path(mj, "js", "mathjax.js").exists()


@pytest.mark.skipif(not _mathjax_available(), reason="node + mathjax-full not installed (npm ci --prefix tools)")
def test_prerendered_output_is_current():
    out = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "prerender_math.py"), "--check"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0, out.stderr
