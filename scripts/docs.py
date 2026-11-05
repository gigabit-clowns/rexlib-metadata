# SPDX-License-Identifier: LGPL-2.1-or-later

"""Build the site of the docs: the Python reference, the README first.

    python -m scripts.docs site

The Python reference goes to `python/`, and the site's root leads to it;
the workflow puts `cargo doc`'s beside it in `rust/`.

The package is the one installed, extension and all. Every page names the
version beside the project; the first is the README alone, its badges left
out and its links to the repository's files made absolute.
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import pdoc
import pdoc.render
from pdoc.render_helpers import to_html
from pygments.formatters import HtmlFormatter

import rexlib_metadata as rxm

ROOT = Path(__file__).resolve().parent.parent
MODULES = (
    "rexlib_metadata",
    "rexlib_metadata.abc",
    "rexlib_metadata.canonical",
    "rexlib_metadata.convention",
    "rexlib_metadata.conventions",
    "rexlib_metadata.formats",
    "rexlib_metadata.pose",
    "rexlib_metadata.registry",
    "rexlib_metadata.result",
    "rexlib_metadata.schema",
)
SOURCE = "https://github.com/gigabit-clowns/rexlib-metadata/blob/main/"
_REDIRECT = """<!doctype html>
<meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=python/">
<link rel="canonical" href="python/">
<a href="python/">rexlib-metadata</a>
"""
_LOCAL_LINK = re.compile(r"\]\((?!https?://|#|docs/assets/)([^)]+)\)")
_BADGES = re.compile(
    r"^<!-- docs-badges:start -->$.*?^<!-- docs-badges:end -->$\n?",
    re.DOTALL | re.MULTILINE,
)


def readme() -> str:
    """Return the README as HTML, without its badges.

    What `docs-badges` comments enclose is left out, and a link to a file
    of the repository is made absolute.
    """
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    text = _BADGES.sub("", text)
    return to_html(_LOCAL_LINK.sub(rf"]({SOURCE}\1)", text))


def build(site: Path) -> None:
    """Write the Python reference into `site`, the README's images with it."""
    output = site / "python"
    pdoc.render.configure(
        docformat="markdown",
        template_directory=ROOT / "docs" / "pdoc",
    )
    pdoc.render.env.globals.update(
        root=MODULES[0],
        version=rxm.__version__,
        readme=readme(),
        dark_code=HtmlFormatter(style="github-dark").get_style_defs(
            ':root[data-theme="dark"] .pdoc-code'
        ),
    )
    pdoc.pdoc(*MODULES, output_directory=output)
    shutil.copytree(
        ROOT / "docs" / "assets", output / "docs" / "assets", dirs_exist_ok=True
    )
    (site / "index.html").write_text(_REDIRECT, encoding="utf-8")
    (site / ".nojekyll").touch()


def main() -> None:
    """Build the reference where the command line says."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    build(parser.parse_args().site)


if __name__ == "__main__":
    main()
