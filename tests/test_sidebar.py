"""Cover for the sidebar behaviour that had no tests at all.

Every case here is a bug that shipped: the list was only ever exercised by
hand, and by-hand testing does not notice that a thumbnail is missing after
an unrelated action, or that a hidden row is still selected.
"""
import types
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

from ax_player import ui
from ax_player.app import AXPlayerWindow

PATHS = [str(Path(r"C:\V") / f"ep{i}.mkv") for i in range(4)]


def _items(paths=PATHS):
    return [{"path": p, "name": Path(p).name, "progress": None} for p in paths]


def _pixmap(width=320, height=180, color="#884422"):
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(color))
    return pixmap


def _has_thumb(sidebar, path):
    pixmap = sidebar._rows[path].data(ui.PIXMAP_ROLE)
    return isinstance(pixmap, QPixmap) and not pixmap.isNull()


@pytest.fixture()
def sidebar(qapp):
    bar = ui.Sidebar()
    bar.set_items("V", _items())
    yield bar
    bar.deleteLater()


# -- thumbnails surviving a change to the list ---------------------------
def test_removing_one_row_keeps_every_other_rows_thumbnail(sidebar):
    """Removal used to rebuild the whole list, which dropped every loaded
    pixmap -- and the rebuilt rows could never get them back (see below), so
    one 移除選取 greyed out the entire sidebar until the folder was reopened."""
    for path in PATHS:
        sidebar.set_thumbnail(path, _pixmap())

    sidebar.remove_rows([PATHS[0]])

    assert PATHS[0] not in sidebar._rows
    assert all(_has_thumb(sidebar, path) for path in PATHS[1:])


def test_relisting_the_same_folder_keeps_loaded_thumbnails(sidebar):
    """The other route to the same loss: a re-sort or an F5 rebuilds the rows
    too. The images are cached by path so a rebuild re-attaches them."""
    sidebar.set_thumbnail(PATHS[1], _pixmap())

    sidebar.set_items("V", _items(), keep_filter=True)

    assert _has_thumb(sidebar, PATHS[1])


def test_thumbnails_of_files_no_longer_listed_are_dropped(sidebar):
    """The cache must not outlive the listing, or browsing folder after
    folder would accumulate every thumbnail ever loaded."""
    for path in PATHS:
        sidebar.set_thumbnail(path, _pixmap())

    sidebar.set_items("Other", _items(PATHS[:1]))

    assert set(sidebar._thumbs) == {PATHS[0]}


def test_a_path_already_asked_for_is_never_asked_for_again(qapp):
    """Why losing a pixmap was permanent rather than a missed repaint: the
    delegate re-asks on the next paint, and this guard drops the request."""
    started = []
    window = types.SimpleNamespace(
        _requested_thumbs={PATHS[0]},
        _thumb_pool=types.SimpleNamespace(start=lambda job: started.append(job)),
        _jobs=None,
    )

    AXPlayerWindow.request_thumbnail(window, Path(PATHS[0]))

    assert not started


# -- the filter and the selection ----------------------------------------
def test_a_hidden_row_is_not_part_of_the_selection(sidebar):
    """Qt does not deselect a row when it is hidden. Selecting three files and
    then searching left all three selected behind the filter, so 移除選取
    removed files the user could no longer see."""
    for index in range(3):
        sidebar._list.item(index).setSelected(True)
    assert len(sidebar._selected_paths()) == 3

    sidebar._search.setText("ep0")

    assert sidebar._selected_paths() == [PATHS[0]]
    assert sidebar._selection_count.text() == "已選取 1 項"


def test_removal_only_emits_the_rows_still_on_screen(sidebar):
    emitted = []
    sidebar.remove_requested.connect(emitted.append)
    for index in range(3):
        sidebar._list.item(index).setSelected(True)
    sidebar._search.setText("ep0")

    sidebar._emit_remove()

    assert emitted == [[PATHS[0]]]


def test_a_relist_of_the_same_folder_keeps_the_search_text(sidebar):
    """A re-sort used to silently clear whatever the user had typed to find
    the file they were about to play."""
    sidebar._search.setText("ep2")

    sidebar.set_items("V", _items(), keep_filter=True)
    assert sidebar._search.text() == "ep2"

    sidebar.set_items("Other", _items())
    assert sidebar._search.text() == ""


# -- the hover preview ---------------------------------------------------
def test_the_sheet_popup_is_pulled_back_onto_the_screen(qapp):
    """672px of contact sheet anchored past the right edge: on a 1366-wide
    laptop every window position past x=376 pushed the last column of the
    grid off-screen, which is a third of what the hover was for."""
    popup = ui.ContactSheetPopup()
    bounds = QApplication.primaryScreen().availableGeometry()

    popup.show_image(_pixmap(672, 384), QPoint(bounds.right() - 40, bounds.bottom() - 40))

    assert bounds.contains(popup.geometry())
    popup.hide_now()
    popup.deleteLater()


# -- memory ---------------------------------------------------------------
def test_a_row_thumbnail_is_scaled_down_before_it_is_kept(qapp, tmp_path):
    """Full-size pixmaps in the item data measured 239.5 MB over 1000 rows
    against 59.8 MB for row-sized ones."""
    source = tmp_path / "thumb.jpg"
    assert _pixmap().save(str(source), "JPG")

    scaled = ui.row_thumbnail_pixmap(source)

    ratio = QApplication.primaryScreen().devicePixelRatio()
    assert not scaled.isNull()
    assert scaled.width() < 320
    assert scaled.width() >= int(ui.THUMB_W * ratio)
    assert scaled.height() >= int(ui.THUMB_H * ratio)
    # Cover-crop still works: the delegate reads only the aspect ratio.
    covered = scaled.size().scaled(
        QSize(ui.THUMB_W, ui.THUMB_H), Qt.AspectRatioMode.KeepAspectRatioByExpanding
    )
    assert covered.width() >= ui.THUMB_W and covered.height() >= ui.THUMB_H


# -- the row menu ---------------------------------------------------------
def test_the_row_menu_offers_the_whole_set_of_actions(sidebar):
    menu = sidebar.build_row_menu([PATHS[0]])

    labels = [action.text() for action in menu.actions() if action.text()]
    assert labels == [
        "播放",
        "標記為已看完",
        "標記為未看",
        "在檔案總管中顯示",
        "複製路徑",
        "從清單移除（不刪檔案）",
    ]
    assert all(action.isEnabled() for action in menu.actions())


def test_actions_that_need_one_file_are_disabled_on_a_multi_selection(sidebar):
    menu = sidebar.build_row_menu(PATHS[:2])

    disabled = [a.text() for a in menu.actions() if a.text() and not a.isEnabled()]
    assert disabled == ["播放", "在檔案總管中顯示"]


def test_marking_watched_from_the_menu_reaches_the_window(sidebar):
    seen = []
    sidebar.watched_changed.connect(lambda paths, watched: seen.append((paths, watched)))
    menu = sidebar.build_row_menu(PATHS[:2])

    next(a for a in menu.actions() if a.text() == "標記為已看完").trigger()

    assert seen == [(PATHS[:2], True)]


def test_the_menu_never_offers_to_delete_anything_from_disk(sidebar):
    """The app's whole contract with the sidebar is that it does not touch
    files on disk, and a right-click menu is exactly where that slips."""
    labels = " ".join(a.text() for a in sidebar.build_row_menu(PATHS).actions())

    assert "刪除" not in labels or "不刪檔案" in labels
    assert "從清單移除（不刪檔案）" in labels


# -- hover preview dismissal ----------------------------------------------
def test_sliding_off_a_row_into_blank_space_takes_the_sheet_down(sidebar):
    """itemEntered fires only for a *valid* index and Leave only when the
    cursor exits the viewport, so the blank area under a short folder was
    covered by neither -- the sheet stayed parked over the video. The list has
    stretch 1, so that blank area is as tall as the window.

    Emitting the signal rather than calling the handler: a handler that is
    never connected would pass the other way round.
    """
    sidebar._hover_path = PATHS[0]
    sidebar._hover_delay.start()

    sidebar._list.viewportEntered.emit()

    assert sidebar._hover_path is None, "still waiting to show a sheet for a row"
    assert not sidebar._hover_delay.isActive(), "the hover-intent timer kept running"
    assert not sidebar._sheet_popup.isVisible()


# -- which row a context menu is about ------------------------------------
def test_a_keyboard_raised_menu_acts_on_the_current_row(sidebar, monkeypatch):
    """Qt synthesises the position for a Menu-key context request from the
    focus widget, not from currentIndex, so itemAt() answers with whatever sits
    at that point -- and _show_row_menu then *rewrites the selection* onto it.
    Arrow to a row, press Menu, and the menu acted on a different file.
    """
    monkeypatch.setattr(sidebar, "_pointer_is_over_rows", lambda: False)
    sidebar._list.setCurrentRow(2)

    target = sidebar._menu_target(QPoint(10_000, 10_000))

    assert target is not None, "a keyboard menu with no row under the point got nothing"
    assert target.data(ui.PATH_ROLE) == PATHS[2]


# -- what a screen reader gets --------------------------------------------
def _accessible(sidebar, path):
    return sidebar._rows[path].data(Qt.ItemDataRole.AccessibleTextRole)


def test_a_row_announces_more_than_its_filename(sidebar):
    """The watched badge, the playing rail and the progress bar are painted by
    _RowDelegate and exist nowhere else, so the accessible name fell back to
    DisplayRole -- the bare filename. A screen-reader user could not tell what
    was playing, what was finished, or where they left off."""
    sidebar.set_playing(PATHS[1])
    sidebar.set_progress(PATHS[2], 30.0, 100.0)
    sidebar.set_watched([PATHS[3]], True)

    assert "播放中" in _accessible(sidebar, PATHS[1])
    assert "已看 30%" in _accessible(sidebar, PATHS[2])
    assert "已看完" in _accessible(sidebar, PATHS[3])
    # An untouched row still says its name and claims nothing else.
    plain = _accessible(sidebar, PATHS[0])
    assert Path(PATHS[0]).name in plain
    assert "播放中" not in plain and "已看" not in plain


def test_the_row_that_stops_playing_stops_saying_so(sidebar):
    """The half that an optimisation here can silently drop.

    set_playing rebuilds the accessible text only for rows whose playing flag
    actually moved -- doing all 3000 took it from 0.48ms to 4.05ms, spent
    recomputing identical strings. Two rows change on every switch, not one,
    and the one that stops is the easy one to forget: it would go on
    announcing 播放中 for a file that is no longer playing.
    """
    sidebar.set_playing(PATHS[1])
    assert "播放中" in _accessible(sidebar, PATHS[1])

    sidebar.set_playing(PATHS[2])

    assert "播放中" in _accessible(sidebar, PATHS[2]), "the new row does not announce itself"
    assert "播放中" not in _accessible(sidebar, PATHS[1]), (
        "the previous row still claims to be playing"
    )


def test_dimmed_text_stays_readable(sidebar):
    """FAINT is not just for small labels: _RowDelegate paints every watched
    episode's filename in it at 13px, so the rows a returning user scans most
    were the least legible. WCAG AA wants 4.5:1 below 18.7px.

    Computed rather than pinned to a hex string, so a future palette change is
    judged on the thing that matters instead of on whether it matched a
    literal.
    """

    def luminance(value):
        value = value.lstrip("#")
        channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        channels = [
            c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
        ]
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    def contrast(fg, bg):
        high, low = sorted((luminance(fg), luminance(bg)), reverse=True)
        return (high + 0.05) / (low + 0.05)

    for background in (ui.PAPER, ui.PAPER_2):
        for colour in (ui.FAINT, ui.MUTED, ui.INK):
            assert contrast(colour, background) >= 4.5, (
                f"{colour} on {background} is {contrast(colour, background):.2f}:1"
            )


def test_right_clicking_blank_space_still_opens_nothing(sidebar, monkeypatch):
    """The mouse path is unchanged: the fallback is gated on the pointer not
    being over the viewport, so a right-click on empty space below the rows
    must not conjure a menu for whatever happens to be current."""
    monkeypatch.setattr(sidebar, "_pointer_is_over_rows", lambda: True)
    sidebar._list.setCurrentRow(2)

    assert sidebar._menu_target(QPoint(10_000, 10_000)) is None


# -- 只看未看完, and the menu's selection rewrite -------------------------
def test_the_unwatched_only_filter_actually_hides_watched_rows(sidebar):
    """A statement-deletion sweep could remove the whole `unwatched_only`
    branch of _apply_filter and the suite stayed green -- the checkbox is a
    listed feature and nothing exercised it.

    The existing filter cover is all about the search box; the two are separate
    conditions in the same loop and only one of them was tested.
    """
    watched = PATHS[1]
    sidebar._rows[watched].setData(ui.WATCHED_ROLE, True)

    sidebar._unwatched.setChecked(True)

    hidden = {p for p in PATHS if sidebar._rows[p].isHidden()}
    assert hidden == {watched}, f"hid {hidden}, expected only the watched row"

    sidebar._unwatched.setChecked(False)
    assert not any(sidebar._rows[p].isHidden() for p in PATHS), "unticking left rows hidden"


def test_marking_watched_while_filtering_takes_the_row_off_the_list(sidebar):
    """set_watched ends in _apply_filter for this reason: with 只看未看完 on,
    ticking a row off has to remove it from the list, not leave it sitting
    there contradicting the filter.

    Deleting that one call left the suite green.
    """
    sidebar._unwatched.setChecked(True)
    assert not sidebar._rows[PATHS[0]].isHidden()

    sidebar.set_watched([PATHS[0]], True)

    assert sidebar._rows[PATHS[0]].isHidden(), "a row stayed on a list that excludes it"
    assert sidebar._rows[PATHS[0]].data(ui.PROGRESS_ROLE) == 0.0, (
        "a finished episode kept its resume bar"
    )


def test_right_clicking_an_unselected_row_acts_on_that_row(sidebar):
    """Every file manager behaves this way, and without it the menu silently
    applies to whatever happened to be selected somewhere else in the list.

    _menu_target only answers *which* row; the selection rewrite that follows
    it is what the menu's own actions read back through _selected_paths.
    """
    sidebar._rows[PATHS[0]].setSelected(True)
    sidebar._rows[PATHS[1]].setSelected(True)
    target = sidebar._rows[PATHS[2]]
    assert not target.isSelected()

    sidebar.claim_selection_for_menu(target)

    assert sidebar._selected_paths() == [PATHS[2]], (
        "the menu would have acted on the old selection"
    )


def test_removing_from_the_playlist_keeps_the_other_rows_intact(sidebar):
    """The same guarantee as the first test in this file, asserted one level up
    -- where the bug actually was.

    That test calls sidebar.remove_rows() directly, so it pins Sidebar. The
    rebuild it describes lived in AXPlayerWindow.remove_from_playlist, whose
    comment still names it: "Not set_items(): rebuilding the list to delete a
    row from it reset the scroll position, the search box and the selection,
    and dropped every loaded thumbnail". Measured: putting `set_items` back
    there left all 133 tests green.

    So this drives the window method and checks what the comment promises --
    thumbnails, search text and selection all surviving a removal.
    """
    window = types.SimpleNamespace(
        _playlist=[Path(p) for p in PATHS],
        sidebar=sidebar,
        player=types.SimpleNamespace(remove_paths=lambda _paths: None),
        _playlist_items=lambda: _items(),
    )
    for path in PATHS:
        sidebar.set_thumbnail(path, _pixmap())
    sidebar._search.setText("ep")
    sidebar._rows[PATHS[2]].setSelected(True)

    AXPlayerWindow.remove_from_playlist(window, [PATHS[0]])

    assert PATHS[0] not in sidebar._rows, "the row was not removed"
    assert all(_has_thumb(sidebar, p) for p in PATHS[1:]), (
        "removal dropped the other rows' thumbnails -- and request_thumbnail "
        "will not regenerate them, so the sidebar stays grey"
    )
    assert sidebar._search.text() == "ep", "the search box was cleared"
    assert sidebar._rows[PATHS[2]].isSelected(), "the selection was lost"


def test_the_context_menu_path_still_claims_the_row_it_opened_on(sidebar):
    """The check above calls claim_selection_for_menu directly, so it pins the
    helper -- not that _show_row_menu still calls it.

    That is HANDOFF §9.39's shape: the helper was split out of _show_row_menu
    *for* testability, and testing only the helper leaves the split itself
    unguarded. A mutation sweep over this loop's own changes found the call
    site was the survivor, one layer above where the test stood.

    _show_row_menu ends at QMenu.exec, which cannot be stubbed from Python.
    build_row_menu is a method, though, so replacing it on the instance lets
    the whole path run without a modal menu appearing.
    """
    shown = []
    sidebar.build_row_menu = lambda paths: types.SimpleNamespace(
        exec=lambda _global_pos: shown.append(list(paths))
    )
    sidebar._rows[PATHS[0]].setSelected(True)
    sidebar._rows[PATHS[1]].setSelected(True)
    target = sidebar._rows[PATHS[2]]
    assert not target.isSelected()

    sidebar._show_row_menu(sidebar._list.visualItemRect(target).center())

    assert shown == [[PATHS[2]]], (
        f"the menu was built for {shown}, not the row it was opened on"
    )
    assert sidebar._selected_paths() == [PATHS[2]]
