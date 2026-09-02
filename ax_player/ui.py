"""Native Qt window chrome + library sidebar.

This replaces the QWebEngineView-based UI the app used to carry. mpv's own
uosc/thumbfast scripts already draw every *playback* control directly onto
the video surface, so the only UI this app ever needed was window chrome
and a folder browser -- which never justified starting a full Chromium
process, plus a QWebChannel handshake, on every single launch just to draw
a list of files.

Dropping the web layer also removes an entire class of bug it created: the
stage "mask" (a hole punched through the web view so mpv's pixels and mouse
input could reach through it), the asynchronous Chromium resize behind the
fullscreen white-gap, dialogs rendering invisibly inside that hole, and the
white flash before the page's dark CSS applied. Native widgets just sit
next to mpv in a layout, so none of those failure modes exist here.

Styling stays scoped to the widgets it's set on: a stylesheet applied to
the whole window would also propagate onto PlayerWidget and paint over
mpv's own surface.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QShortcut,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ax_player import resume, settings

# Ported from the old style.css custom properties (which were in oklch).
PAPER = "#171310"
PAPER_2 = "#1d1815"
PAPER_3 = "#26201a"
INK = "#ece4d9"
MUTED = "#a99781"
# Lightened from #7b6b5a, which measured 3.43:1 on PAPER_2 and 3.6:1 on PAPER
# -- under the 4.5:1 WCAG AA needs for text below 18.7px. It is not only the
# small labels: _RowDelegate paints every *watched* episode's filename in it at
# 13px, so the rows a returning user scans most were the least legible ones.
# This value measures 4.82:1 on PAPER_2 and 5.06:1 on PAPER. (#8f7e6a, the
# obvious next step up, only reaches 4.49 on PAPER_2 -- close enough to look
# right and still short.)
FAINT = "#948373"
ACCENT = "#e3a75c"
ACCENT_HI = "#f0bd7d"
ACCENT_INK = "#191410"
RULE = "#2f2821"
DANGER = "#c1543d"

FONT_UI = '"Segoe UI Variable Text", "Segoe UI", sans-serif'

TITLEBAR_H = 40
SIDEBAR_W = 312
THUMB_W = 116
THUMB_H = 65  # 16:9
ROW_PAD = 6
ROW_GAP = 12
ROW_H = THUMB_H + ROW_PAD * 2 + 2


class _ChromeButton(QAbstractButton):
    """Window-control button, glyph drawn rather than shipped as an image."""

    # The glyph is painted, so there is no text for a screen reader to read and
    # no automatic name to fall back on: without these, all six announce as an
    # unnamed "button". Qt maps a tooltip to QAccessible::Description, which is
    # why the three that had one were not completely silent -- but description
    # is not name, and minimize/maximize/close had neither.
    LABELS = {
        "fluid": "切換 Fluid Motion 補幀",
        "stats": "播放診斷",
        "pin": "視窗置頂",
        "minimize": "最小化",
        "maximize": "最大化",
        "close": "關閉",
    }

    def __init__(self, kind: str, parent: QWidget | None = None, *, width: int = 46):
        super().__init__(parent)
        self._kind = kind
        self._active = False
        self.setFixedWidth(width)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        # TabFocus, not NoFocus: these were unreachable without a mouse, and
        # for 視窗置頂 and 播放診斷 there was no other way in at all -- Alt+F4
        # covers close and nothing covered the rest. Click focus stays off so
        # a mouse user never sees a focus ring they did not ask for.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAccessibleName(self.LABELS.get(kind, kind))
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def set_active(self, on: bool) -> None:
        if self._active != on:
            self._active = on
            self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.width(), TITLEBAR_H)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        hovered = self.underMouse()

        if self._kind == "close" and hovered:
            painter.fillRect(self.rect(), QColor(DANGER))
        elif hovered:
            painter.fillRect(self.rect(), QColor(PAPER_3))
        elif self._active:
            tint = QColor(ACCENT)
            tint.setAlphaF(0.14)
            painter.fillRect(self.rect(), tint)

        if self.hasFocus():
            # Nothing else marks the focused control: the glyph is painted by
            # hand, so Qt draws no platform focus rectangle for it. Tabbing
            # through the titlebar would otherwise move an invisible cursor and
            # Space would activate whatever it had reached.
            ring = QPen(QColor(ACCENT))
            ring.setWidth(2)
            painter.setPen(ring)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

        if self._kind == "close" and hovered:
            stroke = QColor("#f7f7f7")
        elif self._active:
            stroke = QColor(ACCENT)
        elif hovered:
            stroke = QColor(INK)
        else:
            stroke = QColor(MUTED)

        pen = QPen(stroke)
        pen.setWidthF(1.4 if self._kind == "fluid" else 1.2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        cx, cy = self.width() / 2, self.height() / 2
        if self._kind == "minimize":
            painter.drawLine(QPointF(cx - 5, cy), QPointF(cx + 5, cy))
        elif self._kind == "maximize":
            painter.drawRect(QRectF(cx - 4.5, cy - 4.5, 9, 9))
        elif self._kind == "close":
            painter.drawLine(QPointF(cx - 4, cy - 4), QPointF(cx + 4, cy + 4))
            painter.drawLine(QPointF(cx + 4, cy - 4), QPointF(cx - 4, cy + 4))
        elif self._kind == "stats":
            for i, height in enumerate((4.5, 8.0, 6.0)):
                x = cx - 5 + i * 5
                painter.drawLine(QPointF(x, cy + 4), QPointF(x, cy + 4 - height))
        elif self._kind == "pin":
            painter.drawEllipse(QRectF(cx - 3.2, cy - 5.5, 6.4, 6.4))
            painter.drawLine(QPointF(cx, cy + 1), QPointF(cx, cy + 6))
        elif self._kind == "fluid":
            painter.save()
            painter.translate(cx - 8, cy - 8)
            path = QPainterPath(QPointF(1, 8))
            path.cubicTo(2.5, 4, 3.5, 4, 5, 8)
            path.cubicTo(6.5, 12, 7.5, 12, 9, 8)
            path.cubicTo(10.5, 4, 11.5, 4, 13, 4)
            path.cubicTo(14.5, 4, 15, 6, 15, 8)
            painter.drawPath(path)
            painter.restore()


class TitleBar(QWidget):
    """Frameless-window titlebar: brand, now-playing title, window controls."""

    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()
    fluid_clicked = Signal()
    stats_clicked = Signal()
    pin_clicked = Signal()
    drag_started = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(TITLEBAR_H)
        # Without this, a plain QWidget subclass ignores the background/border
        # in its own style sheet rule and just fills with the inherited
        # palette colour -- the child rules below still apply either way,
        # which makes the omission easy to miss.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"""
            TitleBar {{ background: {PAPER_2}; border-bottom: 1px solid {RULE}; }}
            QLabel {{ font-family: {FONT_UI}; background: transparent; }}
            #wordmark {{ color: {INK}; font-size: 12px; font-weight: 700;
                         letter-spacing: 3px; }}
            #nowTitle {{ color: {MUTED}; font-size: 12px; }}
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 0, 0)
        layout.setSpacing(12)

        bulb = _Bulb(self)
        wordmark = QLabel("AX", self)
        wordmark.setObjectName("wordmark")

        self._title = QLabel("", self)
        self._title.setObjectName("nowTitle")
        self._title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        self._fluid = _ChromeButton("fluid", self, width=38)
        self._fluid.setToolTip("切換 Fluid Motion 補幀")
        self._fluid.clicked.connect(self.fluid_clicked)

        self._stats = _ChromeButton("stats", self, width=38)
        self._stats.setToolTip("播放診斷")
        self._stats.clicked.connect(self.stats_clicked)

        self._pin = _ChromeButton("pin", self, width=38)
        self._pin.setToolTip("視窗置頂")
        self._pin.clicked.connect(self.pin_clicked)

        layout.addWidget(bulb)
        layout.addWidget(wordmark)
        layout.addWidget(self._title, 1)
        layout.addWidget(self._pin)
        layout.addWidget(self._stats)
        layout.addWidget(self._fluid)

        for kind, signal in (
            ("minimize", self.minimize_clicked),
            ("maximize", self.maximize_clicked),
            ("close", self.close_clicked),
        ):
            button = _ChromeButton(kind, self)
            button.clicked.connect(signal)
            layout.addWidget(button)

    def set_title(self, title: str) -> None:
        self._title_text = title or ""
        self._elide_title()

    def set_fluid_active(self, on: bool) -> None:
        self._fluid.set_active(on)

    def set_stats_active(self, on: bool) -> None:
        self._stats.set_active(on)

    def set_pin_active(self, on: bool) -> None:
        self._pin.set_active(on)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide_title()

    def _elide_title(self) -> None:
        text = getattr(self, "_title_text", "")
        metrics = self._title.fontMetrics()
        width = max(0, self._title.width())
        self._title.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, width))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_started.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.maximize_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class _Bulb(QWidget):
    """The small glowing amber dot in the brand mark."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(16, 16)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        glow = QColor(ACCENT)
        glow.setAlphaF(0.28)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(1.5, 1.5, 13, 13))
        painter.setBrush(QColor(ACCENT))
        painter.drawEllipse(QRectF(3.5, 3.5, 9, 9))


# -- playlist ---------------------------------------------------------------
PATH_ROLE = Qt.ItemDataRole.UserRole
PIXMAP_ROLE = Qt.ItemDataRole.UserRole + 1
PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 2
WATCHED_ROLE = Qt.ItemDataRole.UserRole + 3
PLAYING_ROLE = Qt.ItemDataRole.UserRole + 4


def refresh_accessible_text(item: QListWidgetItem) -> None:
    """Restate a row's painted state as text a screen reader can read.

    Everything that tells one row from another -- the watched badge, the
    playing rail, the progress bar -- exists only inside _RowDelegate.paint.
    The accessible name falls back to DisplayRole, which is the bare filename,
    so without this a blind user cannot tell what is playing, what is finished,
    or where they left off.

    AccessibleTextRole and not a tooltip: §7 rejected row tooltips because they
    fight the contact-sheet popup for the same hover. This is screen-reader
    only and never renders, so that objection does not apply.
    """
    parts = [str(item.data(Qt.ItemDataRole.DisplayRole) or "")]
    if item.data(PLAYING_ROLE):
        parts.append("播放中")
    if item.data(WATCHED_ROLE):
        parts.append("已看完")
    else:
        ratio = float(item.data(PROGRESS_ROLE) or 0.0)
        if ratio > 0:
            parts.append(f"已看 {round(ratio * 100)}%")
    item.setData(Qt.ItemDataRole.AccessibleTextRole, " · ".join(parts))


class _RowDelegate(QStyledItemDelegate):
    """Draws one playlist row: thumbnail, progress, watched badge, 2-line name.

    A delegate rather than a widget per row: a folder can hold thousands of
    files, and one real widget each would cost far more than painting them.
    """

    def __init__(self, parent, request_thumb) -> None:
        super().__init__(parent)
        self._request_thumb = request_thumb

    def sizeHint(self, _option, _index) -> QSize:  # noqa: N802
        return QSize(10, ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Without this the cover-crop below resamples with the fast (nearest)
        # transform, which is what made the thumbnails visibly jagged. Cheap
        # now that thumbnail_pixmap() hands over an already row-sized image,
        # so the draw is near 1:1 rather than a 320 -> 116 reduction.
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = QRectF(option.rect).adjusted(0, 0, 0, -2)
        playing = bool(index.data(PLAYING_ROLE))
        selected = bool(option.state & option.state.__class__.State_Selected)
        hovered = bool(option.state & option.state.__class__.State_MouseOver)
        watched = bool(index.data(WATCHED_ROLE))

        # Row background + the accent rail marking playing/selected rows.
        if selected:
            tint = QColor(ACCENT)
            tint.setAlphaF(0.20)
            rail = QColor(ACCENT_HI)
        elif playing:
            tint = QColor(ACCENT)
            tint.setAlphaF(0.12)
            rail = QColor(ACCENT)
        elif hovered:
            tint = QColor(PAPER_3)
            rail = None
        else:
            tint = None
            rail = None
        if tint is not None:
            path = QPainterPath()
            path.addRoundedRect(rect, 10, 10)
            painter.fillPath(path, tint)
        if rail is not None:
            painter.fillRect(QRectF(rect.left(), rect.top() + 6, 2, rect.height() - 12), rail)

        thumb_rect = QRectF(rect.left() + ROW_PAD, rect.top() + ROW_PAD, THUMB_W, THUMB_H)
        clip = QPainterPath()
        clip.addRoundedRect(thumb_rect, 4, 4)
        painter.fillPath(clip, QColor(PAPER_3))

        pixmap = index.data(PIXMAP_ROLE)
        path_str = index.data(PATH_ROLE)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            painter.save()
            painter.setClipPath(clip)
            # Cover-crop, same as the old CSS object-fit: cover.
            scaled = pixmap.size().scaled(
                thumb_rect.size().toSize(), Qt.AspectRatioMode.KeepAspectRatioByExpanding
            )
            target = QRectF(
                thumb_rect.center().x() - scaled.width() / 2,
                thumb_rect.center().y() - scaled.height() / 2,
                scaled.width(),
                scaled.height(),
            )
            painter.drawPixmap(target, pixmap, QRectF(pixmap.rect()))
            painter.restore()
        elif path_str:
            # Only rows actually being painted are on screen, so this is the
            # native equivalent of the old IntersectionObserver: a folder of
            # thousands of files doesn't kick off thousands of frame-grabs.
            self._request_thumb(path_str)

        progress = float(index.data(PROGRESS_ROLE) or 0.0)
        bar_rect = QRectF(thumb_rect.left(), thumb_rect.bottom() - 3, thumb_rect.width(), 3)
        if progress > 0:
            painter.fillRect(bar_rect, QColor(0, 0, 0, 102))
            painter.fillRect(
                QRectF(bar_rect.left(), bar_rect.top(), bar_rect.width() * min(1.0, progress), 3),
                QColor(ACCENT),
            )

        if watched:
            badge = QRectF(thumb_rect.right() - 20, thumb_rect.top() + 4, 16, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ACCENT))
            painter.drawEllipse(badge)
            check = QFont(painter.font())
            check.setPixelSize(10)
            painter.setFont(check)
            painter.setPen(QColor(ACCENT_INK))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "✓")

        if playing:
            color = QColor(ACCENT)
        elif watched:
            color = QColor(FAINT)
        elif hovered:
            color = QColor(INK)
        else:
            color = QColor(MUTED)
        text_rect = QRectF(
            thumb_rect.right() + ROW_GAP,
            rect.top() + ROW_PAD,
            max(0.0, rect.right() - ROW_PAD - (thumb_rect.right() + ROW_GAP)),
            THUMB_H,
        )
        _draw_clamped_text(painter, text_rect, str(index.data(Qt.ItemDataRole.DisplayRole) or ""), color)

        painter.restore()


def _draw_clamped_text(painter: QPainter, rect: QRectF, text: str, color: QColor) -> None:
    """Two lines, vertically centred, ellipsis on overflow (CSS line-clamp: 2)."""
    if not text or rect.width() <= 0:
        return
    font = painter.font()
    layout = QTextLayout(text, font)
    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    layout.setTextOption(option)

    metrics = painter.fontMetrics()
    line_height = metrics.height() * 1.35

    layout.beginLayout()
    lines = []
    while len(lines) < 2:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(rect.width())
        lines.append(line)
    layout.endLayout()
    if not lines:
        return

    painter.setPen(color)
    total = line_height * len(lines)
    y = rect.top() + max(0.0, (rect.height() - total) / 2)

    last = lines[-1]
    consumed = last.textStart() + last.textLength()
    overflowed = consumed < len(text)

    for line in lines:
        if overflowed and line is last:
            remainder = text[line.textStart():]
            painter.drawText(
                QRectF(rect.left(), y, rect.width(), line_height),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                metrics.elidedText(remainder, Qt.TextElideMode.ElideRight, int(rect.width())),
            )
        else:
            line.draw(painter, QPointF(rect.left(), y))
        y += line_height


def _fmt(value, suffix: str = "", digits: int = 0) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


class DiagnosticsPanel(QWidget):
    """What mpv and the GPU are actually doing, in the sidebar.

    Not an overlay on the video: mpv renders into a native child window, and
    a plain Qt widget in front of that is drawn into the top-level's backing
    store *behind* it, so it would simply be invisible.

    Only covers what mpv's own stats.lua (Shift+I) can't -- GPU telemetry,
    and a verdict rather than raw numbers to interpret.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("diagnostics")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        self._verdict = QLabel("未播放", self)
        self._verdict.setObjectName("verdict")
        self._verdict.setWordWrap(True)
        self._body = QLabel("", self)
        self._body.setObjectName("diagBody")
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.PlainText)

        layout.addWidget(self._verdict)
        layout.addWidget(self._body)

    def update_data(self, stats: dict, gpu: dict) -> None:
        verdict, ok = self._verdict_for(stats)
        self._verdict.setText(verdict)
        self._verdict.setStyleSheet(f"color: {ACCENT if ok else DANGER};")

        size = "—"
        if stats.get("width") and stats.get("height"):
            size = f"{stats['width']}×{stats['height']}"
        lines = [
            f"影片   {size}  {stats.get('codec') or '—'}",
            f"解碼   {stats.get('hwdec') or '—'}",
            f"幀率   來源 {_fmt(stats.get('source_fps'), digits=2)}"
            f"  →  輸出 {_fmt(stats.get('output_fps'), digits=2)}",
            f"掉幀   解碼 {_fmt(stats.get('dropped'))}  顯示 {_fmt(stats.get('delayed'))}",
            f"A/V    {_fmt(stats.get('avsync'), 's', 3)}",
        ]
        shaders = stats.get("shaders") or 0
        if shaders:
            lines.append(f"著色器 Anime4K · {shaders} 層")
        cache = stats.get("cache")
        if cache is not None:
            lines.append(f"緩衝   {_fmt(cache, 's', 1)}")
        if gpu:
            used, total = gpu.get("vram_used"), gpu.get("vram_total")
            vram = f"{used:.0f}/{total:.0f} MB" if used and total else "—"
            lines.append(
                f"GPU    {_fmt(gpu.get('gpu_util'), '%')}"
                f"  解碼 {_fmt(gpu.get('decoder_util'), '%')}"
                f"  {_fmt(gpu.get('temperature'), '°C')}"
            )
            lines.append(f"VRAM   {vram}")
        self._body.setText("\n".join(lines))

    @staticmethod
    def _verdict_for(stats: dict) -> tuple[str, bool]:
        if not stats.get("playing"):
            return "未播放", True
        source = stats.get("source_fps") or 0
        output = stats.get("output_fps") or 0
        if not source or not output:
            return "播放中（尚未取得幀率）", True
        ratio = output / source
        shaders = stats.get("shaders") or 0
        # Anime4K and RIFE share one GPU, and falling behind looks identical
        # either way -- so when both are on, name the collision instead of
        # leaving the user to guess which one to turn down.
        contention = "，Anime4K 同時運作中（Ctrl+0 可關閉）" if shaders else ""
        if stats.get("interpolating"):
            # Fluid Motion's multiplier isn't exposed here, but anything at or
            # above ~1.8x means it is producing roughly the doubled rate it
            # normally targets; well below that means it can't keep up.
            if ratio >= 1.8:
                return f"補幀運作中 · {ratio:.1f}× ({output:.1f} fps)", True
            return f"補幀落後 · 只有 {ratio:.1f}× ({output:.1f} fps){contention}", False
        if ratio >= 0.95:
            return f"正常播放 · {output:.1f} fps", True
        return f"輸出幀率偏低 · {output:.1f} / {source:.1f} fps{contention}", False


class ContactSheetPopup(QWidget):
    """The floating preview: a real top-level window, not a child widget.

    That distinction matters here specifically -- everything else in this
    app that draws over the video has to live inside AXPlayerWindow's own
    layout, next to PlayerWidget, because a child widget stacked in front of
    mpv's native surface is invisible (see the module docstring in app.py).
    A *separate* top-level window has its own place in the OS window
    z-order and isn't subject to that at all, which is exactly what a hover
    popup needs anyway.
    """

    def __init__(self, parent: QWidget | None = None):
        # A QObject parent for lifetime cleanup only -- the Window-type flags
        # below are what make Qt treat this as a top-level window rather than
        # a child embedded in parent's layout.
        super().__init__(
            parent,
            Qt.WindowType.ToolTip
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setObjectName("sheetPopup")
        self.setStyleSheet(
            f"""
            QWidget#sheetPopup {{
                background: {PAPER_2};
                border: 1px solid {RULE};
                border-radius: 8px;
            }}
            QLabel {{ color: {MUTED}; font-family: {FONT_UI}; font-size: 12px; background: transparent; }}
            QLabel#sheetCaption {{ color: {INK}; font-size: 11px; padding: 2px 2px 0 2px; }}
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        # The row itself clamps the name to two lines, so a long filename is
        # unreadable there. It goes here instead of in a tooltip: a second
        # popup fighting this one for the same hover would be worse than no
        # answer at all, and this window is already what a hover produces.
        self._caption = QLabel(self)
        self._caption.setObjectName("sheetCaption")
        self._caption.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._caption)
        layout.addWidget(self._label)

    def _set_caption(self, text: str) -> None:
        self._caption.setVisible(bool(text))
        self._caption.setText(text)

    def show_loading(self, top_left, caption: str = "") -> None:
        self._set_caption(caption)
        self._label.setPixmap(QPixmap())
        self._label.setText("正在產生預覽…")
        self._label.setFixedSize(200, 60)
        self._place(top_left)

    def show_image(self, pixmap: QPixmap, top_left, caption: str = "") -> None:
        self._set_caption(caption)
        self._label.setText("")
        self._label.setPixmap(pixmap)
        self._label.setFixedSize(pixmap.size())
        self._place(top_left)

    def _place(self, top_left) -> None:
        """Move onto `top_left`, then pull back onto the screen.

        Qt does not reposition a hand-moved ToolTip-flagged window, and this
        one is 672px of sheet wide: on a 1366-wide laptop every window
        position past x=376 pushed the right-hand column off the screen
        entirely, which is the third of the grid the user was reaching for.
        """
        self.adjustSize()
        self.move(top_left)
        screen = self.screen() or QApplication.primaryScreen()
        if screen is not None:
            bounds = screen.availableGeometry()
            size = self.size()
            x = min(top_left.x(), bounds.right() - size.width() + 1)
            y = min(top_left.y(), bounds.bottom() - size.height() + 1)
            self.move(max(bounds.left(), x), max(bounds.top(), y))
        self.show()

    def hide_now(self) -> None:
        self.hide()


class Sidebar(QWidget):
    """Library browser: open actions, search, and the folder's video list."""

    open_folder_clicked = Signal()
    open_file_clicked = Signal()
    open_url_clicked = Signal()
    recursive_changed = Signal(bool)
    sort_changed = Signal(str)
    play_requested = Signal(str)
    remove_requested = Signal(list)
    thumb_requested = Signal(str)
    sheet_requested = Signal(str)
    watched_changed = Signal(list, bool)  # [str path], watched
    reveal_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedWidth(SIDEBAR_W)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)  # see TitleBar
        self.setStyleSheet(_SIDEBAR_QSS)

        self._rows: dict[str, QListWidgetItem] = {}
        # Thumbnails survive a rebuild of the rows. Re-sorting used to throw
        # every loaded pixmap away with the items, and re-asking for them was
        # not free either -- AXPlayerWindow.request_thumbnail keeps a
        # "already asked" set, so anything already generated was simply gone
        # until the folder was reopened. Kept trimmed to the listed files in
        # set_items so it cannot grow across folders.
        self._thumbs: dict[str, QPixmap] = {}
        self._playing: str | None = None
        self._pending_thumbs: set[str] = set()
        self._flush = QTimer(self)
        self._flush.setSingleShot(True)
        self._flush.timeout.connect(self._flush_thumb_requests)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 12, 16)
        layout.setSpacing(12)

        actions = QHBoxLayout()
        actions.setContentsMargins(8, 0, 0, 0)
        actions.setSpacing(8)
        btn_folder = QPushButton("開啟資料夾", self)
        btn_folder.setObjectName("primary")
        btn_folder.clicked.connect(self.open_folder_clicked)
        btn_file = QPushButton("檔案", self)
        btn_file.clicked.connect(self.open_file_clicked)
        btn_url = QPushButton("網址", self)
        btn_url.clicked.connect(self.open_url_clicked)
        actions.addWidget(btn_folder, 1)
        actions.addWidget(btn_file)
        actions.addWidget(btn_url)
        layout.addLayout(actions)

        toggles = QHBoxLayout()
        toggles.setContentsMargins(8, 0, 0, 0)
        toggles.setSpacing(12)
        self._recursive = QCheckBox("含子資料夾", self)
        self._recursive.setObjectName("recursive")
        self._recursive.toggled.connect(self.recursive_changed)
        self._unwatched = QCheckBox("只看未看完", self)
        self._unwatched.setObjectName("recursive")  # same compact styling
        self._unwatched.toggled.connect(lambda _on: self._apply_filter())
        toggles.addWidget(self._recursive)
        toggles.addWidget(self._unwatched)
        toggles.addStretch(1)
        layout.addLayout(toggles)

        self._folder_name = QLabel("尚未開啟資料夾", self)
        self._folder_name.setObjectName("folderName")
        layout.addWidget(self._folder_name)

        self._search = QLineEdit(self)
        self._search.setObjectName("search")
        self._search.setPlaceholderText("搜尋播放清單…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)
        layout.addWidget(self._search)

        sort_row = QHBoxLayout()
        sort_row.setContentsMargins(8, 0, 0, 0)
        sort_row.setSpacing(8)
        sort_label = QLabel("排序", self)
        sort_label.setObjectName("sortLabel")
        self._sort = QComboBox(self)
        self._sort.setObjectName("sort")
        # Data is the persisted key; the label is what the user reads.
        for key, text in (
            (settings.SORT_NAME, "檔名"),
            (settings.SORT_DATE, "修改日期（新到舊）"),
            (settings.SORT_SIZE, "檔案大小（大到小）"),
        ):
            self._sort.addItem(text, key)
        self._sort.currentIndexChanged.connect(
            lambda _i: self.sort_changed.emit(str(self._sort.currentData()))
        )
        sort_row.addWidget(sort_label)
        sort_row.addWidget(self._sort, 1)
        layout.addLayout(sort_row)

        self._selection_bar = QWidget(self)
        selection_layout = QHBoxLayout(self._selection_bar)
        selection_layout.setContentsMargins(8, 0, 8, 0)
        selection_layout.setSpacing(8)
        self._selection_count = QLabel("", self._selection_bar)
        self._selection_count.setObjectName("selectionCount")
        btn_remove = QPushButton("移除選取", self._selection_bar)
        btn_remove.setObjectName("danger")
        btn_remove.clicked.connect(self._emit_remove)
        selection_layout.addWidget(self._selection_count, 1)
        selection_layout.addWidget(btn_remove)
        self._selection_bar.hide()
        layout.addWidget(self._selection_bar)

        self._list = QListWidget(self)
        self._list.setObjectName("playlist")
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setUniformItemSizes(True)
        self._list.setMouseTracking(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setItemDelegate(_RowDelegate(self._list, self._queue_thumb))
        self._list.itemClicked.connect(self._on_item_clicked)
        # Enter on the focused row. Unlike itemClicked this carries no
        # modifier ambiguity, so it plays unconditionally.
        self._list.itemActivated.connect(self._on_item_activated)
        self._list.itemSelectionChanged.connect(self._update_selection_bar)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._show_row_menu)
        self._list.hide()
        layout.addWidget(self._list, 1)

        # Hover preview: itemEntered only fires on *entering* a new row, so
        # leaving the list entirely (mouse exits the viewport without
        # crossing into another row) needs its own signal -- an event filter
        # on the viewport for QEvent.Leave.
        #
        # Blank viewport below the last row is a third case, and neither of
        # those covers it: Qt emits entered() only for a valid index, so
        # sliding off a row into empty space emits viewportEntered() and no
        # Leave at all. The list has stretch 1, so a short folder in a tall
        # window leaves a large blank area right under the rows, and the sheet
        # -- a top-level ToolTip with WindowStaysOnTopHint -- stayed parked
        # over the video until the cursor re-entered a row or left the list.
        self._list.itemEntered.connect(self._on_item_entered)
        self._list.viewportEntered.connect(self._on_viewport_entered)
        self._list.viewport().installEventFilter(self)
        self._hover_path: str | None = None
        self._hover_delay = QTimer(self)
        self._hover_delay.setSingleShot(True)
        self._hover_delay.setInterval(350)  # hover-intent debounce
        self._hover_delay.timeout.connect(self._commit_hover)
        self._sheet_popup = ContactSheetPopup(self)

        delete_key = QShortcut(QKeySequence(Qt.Key.Key_Delete), self._list)
        delete_key.setContext(Qt.ShortcutContext.WidgetShortcut)
        delete_key.activated.connect(self._emit_remove)

        find_key = QShortcut(QKeySequence.StandardKey.Find, self)
        find_key.setContext(Qt.ShortcutContext.WindowShortcut)
        find_key.activated.connect(self._focus_search)

        self._empty = QLabel(
            "選一個資料夾開始播放。\n\n"
            "也可以直接把影片或資料夾拖進來。\n"
            "Ctrl+點擊可多選；播放控制、進度預覽都在畫面上，由 mpv 自己處理。",
            self,
        )
        self._empty.setObjectName("empty")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._empty, 1)

        self.diagnostics = DiagnosticsPanel(self)
        self.diagnostics.hide()
        layout.addWidget(self.diagnostics)

    def restore_state(self, *, recursive: bool, sort_mode: str, unwatched_only: bool) -> None:
        """Apply persisted state without re-emitting the signals that would
        immediately trigger a rescan of a folder that isn't open yet."""
        for widget, value in ((self._recursive, recursive), (self._unwatched, unwatched_only)):
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)
        index = self._sort.findData(sort_mode)
        if index >= 0:
            self._sort.blockSignals(True)
            self._sort.setCurrentIndex(index)
            self._sort.blockSignals(False)

    def unwatched_only(self) -> bool:
        return self._unwatched.isChecked()

    def sort_mode(self) -> str:
        return str(self._sort.currentData())

    # -- population ------------------------------------------------------
    def set_items(self, folder_name: str, items: list[dict], *, keep_filter: bool = False) -> None:
        """Replace the whole list.

        keep_filter is for a re-list of the *same* folder -- a re-sort or an
        F5 rescan. Clearing the search box is right when the folder changes
        and wrong when it does not: re-sorting silently threw away whatever
        the user had typed to find the file they were about to play.
        """
        # Uppercased here rather than in the stylesheet: Qt style sheets have
        # no text-transform.
        self._folder_name.setText(folder_name.upper() if folder_name else "尚未開啟資料夾")
        if not keep_filter:
            self._search.clear()
        self._list.clear()
        self._rows.clear()
        # Anything not in the new listing is gone for good; anything still
        # here keeps the image it already had.
        listed = {entry["path"] for entry in items}
        self._thumbs = {path: pix for path, pix in self._thumbs.items() if path in listed}
        self._hover_delay.stop()
        self._hover_path = None
        self._sheet_popup.hide_now()

        for entry in items:
            item = QListWidgetItem(entry["name"])
            item.setData(PATH_ROLE, entry["path"])
            progress = entry.get("progress") or {}
            duration = float(progress.get("duration") or 0)
            pos = float(progress.get("pos") or 0)
            item.setData(PROGRESS_ROLE, pos / duration if duration > 0 else 0.0)
            item.setData(WATCHED_ROLE, bool(progress.get("watched")))
            item.setData(PLAYING_ROLE, False)
            cached = self._thumbs.get(entry["path"])
            if cached is not None:
                item.setData(PIXMAP_ROLE, cached)
            refresh_accessible_text(item)
            self._list.addItem(item)
            self._rows[entry["path"]] = item

        has_items = bool(items)
        self._list.setVisible(has_items)
        self._empty.setVisible(not has_items)
        # The rows are new; the filter state is not. Without this the
        # "只看未看完" checkbox stayed ticked while every watched row was
        # shown -- on every folder change, and on startup, where
        # restore_state() ticks it with signals blocked so nothing else ever
        # applies it.
        self._apply_filter()
        self._update_selection_bar()
        if self._playing:
            self.set_playing(self._playing)

    def set_thumbnail(self, path: str, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        self._thumbs[path] = pixmap
        item = self._rows.get(path)
        if item is not None:
            item.setData(PIXMAP_ROLE, pixmap)

    def remove_rows(self, paths: list[str]) -> None:
        """Take these rows out without rebuilding the list.

        Rebuilding via set_items() is what "移除選取" used to do, and it cost
        far more than the removal: the scroll position jumped back to the top,
        the search box was cleared, the selection was lost -- and every
        thumbnail went permanently blank, because the rebuilt rows re-asked
        for images that AXPlayerWindow.request_thumbnail had already recorded
        as asked-for and would therefore never generate again. Nothing short
        of reopening the folder brought them back.
        """
        for path in paths:
            item = self._rows.pop(path, None)
            self._thumbs.pop(path, None)
            if item is None:
                continue
            row = self._list.row(item)
            if row >= 0:
                self._list.takeItem(row)
        if self._playing in paths:
            self._playing = None
        if self._hover_path in paths:
            self._hover_delay.stop()
            self._hover_path = None
            self._sheet_popup.hide_now()
        has_items = self._list.count() > 0
        self._list.setVisible(has_items)
        self._empty.setVisible(not has_items)
        self._update_selection_bar()

    def set_playing(self, path: str) -> None:
        self._playing = path
        for key, item in self._rows.items():
            item.setData(PLAYING_ROLE, key == path)
            refresh_accessible_text(item)
        current = self._rows.get(path)
        if current is not None:
            self._list.scrollToItem(current, QAbstractItemView.ScrollHint.EnsureVisible)

    def set_progress(self, path: str, pos: float, duration: float) -> None:
        item = self._rows.get(path)
        if item is None or duration <= 0:
            return
        ratio = pos / duration
        item.setData(PROGRESS_ROLE, ratio)
        item.setData(WATCHED_ROLE, ratio >= resume.WATCHED_THRESHOLD)
        refresh_accessible_text(item)

    # -- interaction -----------------------------------------------------
    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return  # multi-select gesture, not a play request
        path = item.data(PATH_ROLE)
        if path:
            self.play_requested.emit(str(path))

    # -- hover preview -----------------------------------------------------
    def _on_item_entered(self, item: QListWidgetItem) -> None:
        path = item.data(PATH_ROLE)
        self._hover_path = str(path) if path else None
        self._hover_delay.stop()
        self._sheet_popup.hide_now()
        if self._hover_path:
            self._hover_delay.start()

    def _commit_hover(self) -> None:
        if not self._hover_path:
            return
        self._sheet_popup.show_loading(self._popup_pos(), self._caption_for(self._hover_path))
        self.sheet_requested.emit(self._hover_path)

    def _caption_for(self, path: str) -> str:
        item = self._rows.get(path)
        return item.text() if item is not None else Path(path).name

    def show_contact_sheet(self, path: str, pixmap: QPixmap) -> None:
        # A slow generation can finish after the hover has already moved to
        # another row (or left the list) -- stale results are dropped rather
        # than popping a preview for something the user isn't over any more.
        if path != self._hover_path:
            return
        if pixmap.isNull():
            self._sheet_popup.hide_now()
            return
        self._sheet_popup.show_image(pixmap, self._popup_pos(), self._caption_for(path))

    def _popup_pos(self) -> QPoint:
        # To the right of the sidebar, pinned near the top -- not level with
        # the hovered row. Following the row was the original intent and the
        # comment claimed it for a while, but a fixed anchor is what is
        # actually wanted here: the sheet is up to nine cells tall, so tracking
        # a row near the bottom of a long list would push it off-screen, and
        # a popup that jumps as the cursor slides down the list is worse to
        # read than one that stays put. Clear of the rows either way, so it
        # never covers what triggered it.
        return self.mapToGlobal(QPoint(self.width(), 8))

    def _pointer_is_over_rows(self) -> bool:
        """True when the physical cursor is inside the list's viewport.

        The one thing that separates a right-click from a keyboard-raised menu
        without guessing at Qt's synthesised position: a click cannot have come
        from a viewport the pointer is not in. Keeps the mouse path exactly as
        it was -- right-clicking blank space still opens nothing.
        """
        viewport = self._list.viewport()
        return viewport.rect().contains(viewport.mapFromGlobal(QCursor.pos()))

    def _dismiss_hover(self) -> None:
        """Forget the pending hover and take the sheet down."""
        self._hover_delay.stop()
        self._hover_path = None
        self._sheet_popup.hide_now()

    def _on_viewport_entered(self) -> None:
        # The cursor is inside the list but over no row -- the blank area under
        # a short folder. Qt reports that here rather than through entered() or
        # Leave, so without this the sheet for the last row hovered stays up.
        self._dismiss_hover()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._list.viewport() and event.type() == event.Type.Leave:
            self._dismiss_hover()
        return super().eventFilter(obj, event)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        path = item.data(PATH_ROLE)
        if path:
            self.play_requested.emit(str(path))

    # -- row menu ----------------------------------------------------------
    def _menu_target(self, pos) -> QListWidgetItem | None:
        """Which row a context-menu request is about.

        Split out of _show_row_menu so it can be tested: that one ends in
        QMenu.exec, which cannot be stubbed from Python and parks the test on a
        real modal menu.
        """
        item = self._list.itemAt(pos)
        if item is None and not self._pointer_is_over_rows():
            # Raised from the keyboard (Menu key / Shift+F10). Qt synthesises
            # the position from the focus widget rather than from currentIndex,
            # so itemAt() lands on whatever happens to sit there -- blank space,
            # or a row the user never arrowed to, which the selection rewrite
            # in _show_row_menu would then make current. Arrow to episode 20,
            # press Menu, and 標記已看 acted on the row at the top of the
            # viewport instead.
            return self._list.currentItem()
        return item

    def _show_row_menu(self, pos) -> None:
        item = self._menu_target(pos)
        if item is None:
            return
        # Right-clicking a row outside the current selection acts on that row,
        # the way every file manager behaves -- otherwise the menu would
        # silently apply to whatever happened to be selected elsewhere.
        if not item.isSelected():
            self._list.clearSelection()
            item.setSelected(True)
            self._list.setCurrentItem(item)
        paths = self._selected_paths()
        if not paths:
            return
        # The sheet popup is a ToolTip window and would sit on top of the menu.
        self._hover_delay.stop()
        self._sheet_popup.hide_now()
        self.build_row_menu(paths).exec(self._list.viewport().mapToGlobal(pos))

    def build_row_menu(self, paths: list[str]) -> QMenu:
        """The menu for these rows, built but not shown.

        Separate from _show_row_menu because QMenu.exec is a modal loop that
        cannot be stubbed out from Python -- a test that called it simply
        blocked on a real menu waiting for a real click. Everything worth
        checking is in what this returns.
        """
        single = len(paths) == 1
        menu = QMenu(self)
        menu.addAction("播放", lambda: self.play_requested.emit(paths[0])).setEnabled(single)
        menu.addSeparator()
        menu.addAction("標記為已看完", lambda: self.watched_changed.emit(paths, True))
        menu.addAction("標記為未看", lambda: self.watched_changed.emit(paths, False))
        menu.addSeparator()
        menu.addAction(
            "在檔案總管中顯示", lambda: self.reveal_requested.emit(paths[0])
        ).setEnabled(single)
        menu.addAction("複製路徑", lambda: QApplication.clipboard().setText("\n".join(paths)))
        menu.addSeparator()
        # Wording kept explicit: this app has never deleted anything off disk
        # and this menu is not where that changes.
        menu.addAction("從清單移除（不刪檔案）", self._emit_remove)
        return menu

    def set_watched(self, paths: list[str], watched: bool) -> None:
        """Reflect a hand-made watched/unwatched mark back onto the rows."""
        for path in paths:
            item = self._rows.get(path)
            if item is None:
                continue
            item.setData(WATCHED_ROLE, watched)
            if watched:
                # Matches what resume.set_watched stores: a finished episode
                # should not also sit at "resume from 23:58".
                item.setData(PROGRESS_ROLE, 0.0)
            refresh_accessible_text(item)
        self._apply_filter()

    def _focus_search(self) -> None:
        self._search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search.selectAll()

    def _selected_paths(self) -> list[str]:
        """The selected rows the user can actually see.

        Qt does not deselect a row when it is hidden, and _apply_filter only
        hides. So selecting three files and then typing in the search box left
        all three selected behind the filter: the bar still claimed "已選取 3
        項" while one row was on screen, and 移除選取 then removed two files
        the user could no longer see.
        """
        return [
            str(item.data(PATH_ROLE))
            for item in self._list.selectedItems()
            if not item.isHidden() and item.data(PATH_ROLE)
        ]

    def _emit_remove(self) -> None:
        paths = self._selected_paths()
        if paths:
            self.remove_requested.emit(paths)

    def _update_selection_bar(self) -> None:
        count = len(self._selected_paths())
        self._selection_bar.setVisible(count > 0)
        self._selection_count.setText(f"已選取 {count} 項" if count else "")

    def _apply_filter(self, _text: str | None = None) -> None:
        needle = self._search.text().strip().lower()
        unwatched_only = self._unwatched.isChecked()
        for index in range(self._list.count()):
            item = self._list.item(index)
            hidden = bool(needle) and needle not in item.text().lower()
            if unwatched_only and item.data(WATCHED_ROLE):
                hidden = True
            item.setHidden(hidden)
        # Hiding a row does not deselect it, so the count the bar shows (and
        # what 移除選取 would act on) changes with the filter.
        self._update_selection_bar()

    def _queue_thumb(self, path: str) -> None:
        # Called from the delegate's paint; defer the actual request so
        # nothing re-enters the item model while it is being painted.
        self._pending_thumbs.add(path)
        if not self._flush.isActive():
            self._flush.start(0)

    def _flush_thumb_requests(self) -> None:
        pending, self._pending_thumbs = self._pending_thumbs, set()
        for path in pending:
            self.thumb_requested.emit(path)

    # -- signature: film perforation down the sidebar's outer edge --------
    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        dot = QColor(ACCENT)
        dot.setAlphaF(0.42)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot)
        y = 5.0
        while y < self.height():
            painter.drawEllipse(QPointF(5, y), 2.4, 2.4)
            y += 26


_SIDEBAR_QSS = f"""
Sidebar {{ background: {PAPER_2}; border-right: 1px solid {RULE}; }}
QWidget {{ font-family: {FONT_UI}; font-size: 13px; color: {INK}; }}

QPushButton {{
    padding: 7px 12px;
    border: 1px solid {RULE};
    border-radius: 6px;
    background: {PAPER_3};
    color: {INK};
    font-size: 12px;
}}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton#danger:hover {{ border-color: {DANGER}; color: {DANGER}; }}
/* Focus rings, drawn explicitly: once a widget carries a stylesheet with a
   border, QStyleSheetStyle stops painting the platform focus rectangle. Only
   QLineEdit#search had one, so tabbing from the search box through 開啟資料夾,
   檔案, 網址, 含子資料夾, 只看未看完 and 排序 moved an invisible cursor and
   Space activated whatever it had reached. */
QPushButton:focus {{ border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton#danger:focus {{ border-color: {DANGER}; color: {DANGER}; }}

QCheckBox#recursive {{ color: {MUTED}; font-size: 11px; padding-left: 8px; }}
QCheckBox#recursive::indicator {{
    width: 13px; height: 13px;
    border: 1px solid {RULE};
    border-radius: 3px;
    background: {PAPER_3};
}}
QCheckBox#recursive::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox#recursive:focus {{ color: {ACCENT}; }}
QCheckBox#recursive:focus::indicator {{ border-color: {ACCENT}; }}
QCheckBox#recursive::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QLabel#folderName {{
    color: {FAINT};
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 2px;
    padding: 0 8px 8px 8px;
    border-bottom: 1px solid {RULE};
}}
QLabel#selectionCount {{ color: {MUTED}; font-size: 11px; }}
QLabel#sortLabel {{ color: {MUTED}; font-size: 11px; }}

QComboBox#sort {{
    padding: 4px 8px;
    border: 1px solid {RULE};
    border-radius: 6px;
    background: {PAPER_3};
    color: {INK};
    font-size: 11px;
}}
QComboBox#sort:hover {{ border-color: {ACCENT}; }}
QComboBox#sort:focus {{ border-color: {ACCENT}; color: {ACCENT}; }}
/* Qt draws its own arrow here: the CSS border-triangle trick renders as a
   stray dash rather than a triangle in Qt style sheets. */
QComboBox#sort::drop-down {{ border: none; width: 18px; }}
QComboBox#sort QAbstractItemView {{
    background: {PAPER_3};
    color: {INK};
    border: 1px solid {RULE};
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_INK};
    outline: none;
}}
QLabel#empty {{ color: {MUTED}; font-size: 12px; padding: 0 8px; }}

QMenu {{
    background: {PAPER_3};
    border: 1px solid {RULE};
    padding: 4px;
    color: {INK};
    font-size: 12px;
}}
QMenu::item {{ padding: 5px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT}; color: {ACCENT_INK}; }}
QMenu::item:disabled {{ color: {FAINT}; }}
QMenu::separator {{ height: 1px; background: {RULE}; margin: 4px 6px; }}

QWidget#diagnostics {{
    background: {PAPER_3};
    border: 1px solid {RULE};
    border-radius: 6px;
}}
QLabel#verdict {{ color: {ACCENT}; font-size: 11px; font-weight: 600; }}
QLabel#diagBody {{
    color: {MUTED};
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 10px;
}}

QLineEdit#search {{
    margin: 0 8px;
    padding: 6px 10px;
    border: 1px solid {RULE};
    border-radius: 6px;
    background: {PAPER_3};
    color: {INK};
    font-size: 12px;
}}
QLineEdit#search:focus {{ border-color: {ACCENT}; }}

QListWidget#playlist {{
    background: transparent;
    border: none;
    outline: none;
    padding-left: 8px;
}}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {RULE}; border-radius: 4px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {FAINT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
"""


def thumbnail_pixmap(path: str | Path) -> QPixmap:
    """The image at full size -- for the contact sheet popup, which shows it."""
    pixmap = QPixmap()
    pixmap.load(str(path))
    return pixmap


def row_thumbnail_pixmap(path: str | Path) -> QPixmap:
    """The same image, scaled once to the size a row actually draws it at.

    A sidebar thumbnail is generated 320px wide and drawn into 116x65. Keeping
    the full-size pixmap in the item meant every row the user scrolled past
    stayed in memory at 225 KiB: measured over 1000 distinct thumbnails, the
    process went from 16.7 MB to 239.5 MB. Scaling here first put the same
    1000 rows at 59.8 MB, and the delegate's redraw becomes a near-1:1 blit
    instead of a reduction on every paint.

    Expanding, not fitting: the delegate cover-crops, so the pixmap has to
    cover the cell in both axes -- and it reads only the aspect ratio from
    here, so a slightly larger image still crops identically.
    """
    pixmap = thumbnail_pixmap(path)
    if pixmap.isNull():
        return pixmap
    screen = QApplication.primaryScreen()
    ratio = screen.devicePixelRatio() if screen is not None else 1.0
    target = QSize(int(THUMB_W * ratio), int(THUMB_H * ratio))
    if pixmap.width() <= target.width() and pixmap.height() <= target.height():
        return pixmap
    return pixmap.scaled(
        target,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
