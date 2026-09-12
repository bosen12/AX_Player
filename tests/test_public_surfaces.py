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


def test_build_uses_only_the_release_python_314_interpreter():
    commands = [
        line.strip().lower()
        for line in _read("build.bat").splitlines()
        if line.strip() and not line.strip().lower().startswith("rem ")
    ]
    assert "py -3.14 -m pyinstaller --noconfirm --clean axplayer.spec" in commands
    assert any(line.startswith("py -3.14 -m pip ") for line in commands)
    assert not any(re.search(r"(?<![\w.-])python\s+-m\s+", line) for line in commands)
    assert not any(re.search(r"(?<![\w.-])py\s+-3(?:\s|$)", line) for line in commands)


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


# --- the other way the page drifts: ids ---------------------------------
#
# docs/app.js and docs/index.html are joined by bare id strings. app.js grabs
# six of them up front and then calls lib.addEventListener(...) with no null
# check, so a renamed id throws and the whole demo -- the page's one piece of
# interactive content -- silently does nothing. Nobody's install breaks, which
# is why this sits here at a lower weight than the sibling project's
# test_dom_contract.py, where the same shape leaves the app unable to start.
#
# This file already exists because the published page drifted twice: the
# version chip sat two releases behind, and the license said MIT for ten days
# after the relicense. A third drift class in the same hand-edited file is not
# a hypothetical.


def _page_ids() -> set[str]:
    return set(re.findall(r'\bid="([^"]+)"', _read("docs/index.html")))


def _js_lookups() -> set[str]:
    return set(re.findall(
        r"""getElementById\(\s*["']([^"']+)["']""", _read("docs/app.js")
    ))


def test_the_id_extraction_finds_both_sides():
    """Guards the guard: either side coming back empty would make the two
    checks below pass while comparing nothing."""
    assert len(_page_ids()) >= 8, sorted(_page_ids())
    assert len(_js_lookups()) >= 5, sorted(_js_lookups())


def test_every_id_the_demo_reaches_for_is_on_the_page():
    missing = sorted(_js_lookups() - _page_ids())
    assert not missing, (
        f"docs/app.js looks up ids the page does not define: {missing}. "
        "getElementById answers null, and the first unguarded use of one "
        "throws -- taking the rest of the demo with it, in a console the "
        "visitor never opens."
    )


def test_every_in_page_link_lands_somewhere():
    """The skip link, the section rail and the nav all point at #ids. A dead
    one scrolls nowhere, which looks the same as a link nobody clicked."""
    page = _read("docs/index.html")
    targets = set(re.findall(r'href="#([^"]+)"', page))
    assert len(targets) >= 5, f"only found {sorted(targets)}"
    dead = sorted(targets - _page_ids())
    assert not dead, f"these in-page links point at ids that do not exist: {dead}"
