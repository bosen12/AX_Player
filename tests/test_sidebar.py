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
