"""The published site claims a license. It has to be the one in LICENSE.

b85e59d ("Release under GPLv2+") changed LICENSE, README.md and NOTICE.md.
It did not touch docs/index.html, so the site went on telling visitors the
source was MIT for ten days -- in four places, including the <meta> blurb
search engines quote.

That is §9.40's three questions again, with a legal edge: the two sides are
joined by nothing but a repeated string, being wrong raises nothing, and a
wrong answer is indistinguishable from a right one to anyone reading the page.

Nothing here writes the license name out. LICENSE is the ground truth, the
README badge is the short form the project uses for it, and the site is checked
against the badge -- so retagging the license in the two authoritative places
is what makes this test demand the site follow.

Anime4K is credited as MIT on that page and stays MIT: it is somebody else's
license, not a claim about this project. The scoping rule is the word 授權,
which the project uses for its own license and not for the third-party credits.
"""
import re
from pathlib import Path

import pytest

import ax_player

SURFACES = ("README.md", "docs/index.html")

# Enough of the common short names that a switch to any of them is noticed.
LICENSE_TOKEN = r"MIT|GPLv?[0-9.]*\+?|LGPLv?[0-9.+]*|AGPLv?[0-9.+]*|Apache[- ]?2?[.0-9]*|BSD[- ]?[0-9]*[- ]?[A-Za-z]*|MPLv?[0-9.]*|ISC"


def _repo() -> Path:
    """Anchored through the package file, never the cwd: a build.bat test here
    once read a cwd-relative path and passed against a different repo's file."""
    return Path(ax_player.__file__).resolve().parent.parent


def _read(name: str) -> str:
    return (_repo() / name).read_text(encoding="utf-8", errors="replace")


def _badge_license() -> str:
    """The short form the project uses for itself, taken from README's badge."""
    match = re.search(r"img\.shields\.io/badge/license-([^-\s)]+)-", _read("README.md"))
    assert match, "README has no license badge to derive the short form from"
    return match.group(1).replace("%2B", "+").replace("%20", " ")


def test_the_surfaces_under_test_are_this_repos():
    for name in SURFACES:
        path = (_repo() / name).resolve()
        assert path.is_relative_to(_repo()), f"{path} is outside {_repo()}"
        assert path.is_file(), f"{path} is missing"


def test_license_file_and_readme_badge_agree():
    """The badge is only usable as the short form while it matches the real
    thing. LICENSE is the verbatim GPLv2 text; its heading is the ground truth."""
    heading = "\n".join(_read("LICENSE").splitlines()[:3]).upper()
    badge = _badge_license().upper()
    if "GNU GENERAL PUBLIC LICENSE" in heading:
        assert badge.startswith("GPL"), (
            f"LICENSE is the GNU GPL but README's badge says {_badge_license()}"
        )
    elif "MIT" in heading:
        assert badge.startswith("MIT"), (
            f"LICENSE is MIT but README's badge says {_badge_license()}"
        )
    else:
        pytest.fail(f"unrecognised LICENSE heading: {heading!r}")


def test_the_scoping_rule_actually_finds_the_sites_claims():
    """Guards the guard. If 授權 stops appearing next to a license name -- a
    rewording, a translation -- the check below would pass by inspecting
    nothing, which is how a green suite hides a stale page."""
    claims = re.findall(rf"({LICENSE_TOKEN})\s*授權", _read("docs/index.html"))
    assert len(claims) >= 3, f"only found {claims} on the site"


@pytest.mark.parametrize("surface", SURFACES)
def test_every_license_claim_names_the_projects_own_license(surface):
    expected = _badge_license()
    claims = re.findall(rf"({LICENSE_TOKEN})\s*授權", _read(surface))
    wrong = [claim for claim in claims if claim != expected]
    assert not wrong, (
        f"{surface} claims {wrong} but this project is {expected}. "
        "b85e59d relicensed without updating the site, and it stood for ten days."
    )


def test_the_search_engine_blurb_names_the_right_license():
    """The <meta> description is the one claim that never says 授權, so the
    scoping rule above cannot see it -- and it is the copy search results quote."""
    page = _read("docs/index.html")
    match = re.search(r'<meta name="description" content="([^"]*)"', page)
    assert match, "the site lost its meta description"
    # No trailing \b: it cannot match after the "+" in a name like GPLv2+.
    named = re.findall(rf"(?<![A-Za-z])({LICENSE_TOKEN})", match.group(1))
    assert named, "the blurb names no license at all"
    assert all(name == _badge_license() for name in named), (
        f"the blurb says {named}, this project is {_badge_license()}"
    )
