"""Theme (dark + light palettes) and the small shared widgets.

Qt style sheets are string based, so the palette lives in one dict that is both
fed to the QSS template and used by widgets that paint themselves (score bars,
status chips, sparkline-ish bits).
"""
from __future__ import annotations

import webbrowser
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

PALETTES: dict[str, dict[str, str]] = {
    "midnight": {
        "bg": "#0f131c", "surface": "#161c28", "surface_alt": "#1d2534", "surface_hi": "#232c3e",
        "border": "#28324a", "text": "#e9edf6", "muted": "#98a4bd", "accent": "#4f8cff",
        "accent_text": "#ffffff", "success": "#3ecf8e", "warning": "#f2a63b",
        "danger": "#e0576b", "info": "#59b0f6", "shadow": "rgba(0,0,0,140)",
    },
    "daylight": {
        "bg": "#f3f5fb", "surface": "#ffffff", "surface_alt": "#eef1f9", "surface_hi": "#e4e9f6",
        "border": "#d5dcec", "text": "#172033", "muted": "#5d6a86", "accent": "#2f6bff",
        "accent_text": "#ffffff", "success": "#1a9e6a", "warning": "#c67a09",
        "danger": "#cf3b52", "info": "#1f7fd0", "shadow": "rgba(23,32,51,60)",
    },
    "blackgreen": {
        "bg": "#050b07", "surface": "#0c1711", "surface_alt": "#132219",
        "surface_hi": "#1a3324", "border": "#2c5a3e", "text": "#e9f7ef",
        "muted": "#9fb8ab", "accent": "#34e573", "accent_text": "#03150a",
        "success": "#3ddc85", "warning": "#f0a93b", "danger": "#ef5f70",
        "info": "#38c7b8", "shadow": "rgba(0,0,0,200)",
    },
}
DEFAULT_THEME = "midnight"

QSS = """
* { font-family: "%(font)s"; outline: none; }
QWidget { color: %(text)s; font-size: 13px; }
QMainWindow, QDialog { background: %(bg)s; }
QToolTip { background: %(surface_hi)s; color: %(text)s; border: 1px solid %(border)s;
    padding: 6px 10px; border-radius: 6px; font-size: 12px; }

#Sidebar { background: %(surface)s; border-right: 1px solid %(border)s; }
#SidebarTitle { font-size: 17px; font-weight: 800; letter-spacing: 1px; color: %(text)s; }
#SidebarSubtitle { color: %(muted)s; font-size: 11px; letter-spacing: 2px; }
#SidebarFooter { color: %(muted)s; font-size: 11px; }

QPushButton#NavButton {
    text-align: left; padding: 10px 16px; border: none; border-radius: 9px;
    color: %(muted)s; font-size: 13px; font-weight: 600; background: transparent;
}
QPushButton#NavButton:hover { background: %(surface_alt)s; color: %(text)s; }
QPushButton#NavButton:checked { background: %(surface_hi)s; color: %(text)s;
    border-left: 3px solid %(accent)s; }

#PageTitle { font-size: 22px; font-weight: 800; }
#PageSubtitle { color: %(muted)s; font-size: 12px; }
#SectionTitle { font-size: 15px; font-weight: 700; }
#Muted { color: %(muted)s; }
#Small { font-size: 11px; color: %(muted)s; }
#H1 { font-size: 26px; font-weight: 800; }

QFrame#Card { background: %(surface)s; border: 1px solid %(border)s; border-radius: 14px; }
QFrame#AccentCard { background: %(surface_alt)s; border: 1px solid %(accent)s; border-radius: 14px; }
QFrame#Toast { border-radius: 10px; padding: 2px; }
QLabel#StatValue { font-size: 24px; font-weight: 800; }
QLabel#StatLabel { color: %(muted)s; font-size: 11px; letter-spacing: 1px; }
QLabel#Chip { border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 700; }

QPushButton {
    background: %(surface_alt)s; border: 1px solid %(border)s; border-radius: 9px;
    padding: 7px 15px; font-weight: 600; color: %(text)s;
}
QPushButton:hover { background: %(surface_hi)s; border-color: %(accent)s; }
QPushButton:pressed { background: %(surface)s; border-color: %(accent)s; }
QPushButton:disabled { color: %(muted)s; background: %(surface)s; border-color: %(border)s; }
QPushButton#Primary { background: %(accent)s; border: 1px solid %(accent)s; color: %(accent_text)s; }
QPushButton#Primary:hover { background: %(accent)s; border-color: %(accent)s; }
QPushButton#Danger { color: %(danger)s; border-color: %(danger)s; background: transparent; }
QPushButton#Danger:hover { background: %(surface_alt)s; border-color: %(danger)s; }
QPushButton#Ghost { background: transparent; border: 1px solid %(border)s; border-radius: 9px; color: %(accent)s; }
QPushButton#Ghost:hover { background: %(surface_alt)s; border-color: %(accent)s; }

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox, QDateEdit {
    background: %(surface_alt)s; border: 1px solid %(border)s; border-radius: 9px;
    padding: 7px 10px; selection-background-color: %(accent)s; selection-color: %(text)s;
}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QSpinBox:hover, QComboBox:hover, QDateEdit:hover {
    border-color: %(accent)s;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus, QDateEdit:focus {
    border: 1px solid %(accent)s; background: %(surface)s;
}
QComboBox::drop-down { subcontrol-origin: border; subcontrol-position: top right;
    width: 24px; border-left: 1px solid %(border)s; border-top-right-radius: 9px;
    border-bottom-right-radius: 9px; background: %(surface_hi)s; }
QComboBox::down-arrow { width: 9px; height: 9px; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; width: 20px; background: %(surface_hi)s; border: none;
    border-left: 1px solid %(border)s; }
QSpinBox::up-button { subcontrol-position: top right; border-top-right-radius: 9px;
    margin: 1px 1px 0 0; }
QSpinBox::down-button { subcontrol-position: bottom right; border-bottom-right-radius: 9px;
    margin: 0 1px 1px 0; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: %(accent)s; }
QSpinBox::up-arrow, QSpinBox::down-arrow { width: 7px; height: 7px; }
QSpinBox, QDoubleSpinBox { padding-right: 24px; }
QComboBox QAbstractItemView { background: %(surface)s; border: 1px solid %(border)s;
    border-radius: 8px; padding: 4px; selection-background-color: %(surface_hi)s;
    selection-color: %(text)s; }
QComboBox QAbstractItemView::item { padding: 6px 8px; border-radius: 6px; }

QCheckBox, QRadioButton { spacing: 7px; }
QCheckBox::indicator, QRadioButton::indicator { width: 16px; height: 16px; border-radius: 5px;
    border: 1px solid %(border)s; background: %(surface_alt)s; }
QCheckBox::indicator:hover, QRadioButton::indicator:hover { border-color: %(accent)s; }
QCheckBox::indicator:checked { background: %(accent)s; border-color: %(accent)s; }

QTableWidget, QTableView {
    background: %(surface)s; alternate-background-color: %(surface_alt)s;
    border: 1px solid %(border)s; border-radius: 12px; gridline-color: %(border)s;
    selection-background-color: %(surface_hi)s; selection-color: %(text)s;
}
QHeaderView::section { background: %(surface_alt)s; color: %(muted)s; border: none;
    border-bottom: 1px solid %(border)s; padding: 8px 10px; font-weight: 700; font-size: 11px; }
QTableWidget::item { padding: 5px 8px; border: none; }
QTableWidget::item:hover { background: %(surface_hi)s; }
QTableWidget::item:selected { background: %(surface_hi)s; color: %(text)s; }

QTabWidget::pane { border: 1px solid %(border)s; border-radius: 12px; top: -1px; }
QTabBar::tab { background: transparent; padding: 8px 16px; color: %(muted)s; font-weight: 600;
    border: none; border-radius: 8px 8px 0 0; }
QTabBar::tab:hover { background: %(surface_alt)s; color: %(text)s; }
QTabBar::tab:selected { color: %(text)s; border-bottom: 2px solid %(accent)s; }

QScrollBar:vertical { background: transparent; width: 11px; margin: 2px; }
QScrollBar::handle:vertical { background: %(border)s; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(accent)s; width: 11px; }
QScrollBar:horizontal { background: transparent; height: 11px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(border)s; border-radius: 5px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: %(accent)s; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }

QProgressBar { background: %(surface_alt)s; border: 1px solid %(border)s; border-radius: 8px;
    height: 12px; text-align: center; font-size: 10px; color: %(muted)s; }
QProgressBar#Busy { border: none; background: %(surface_hi)s; }
QProgressBar::chunk { border-radius: 7px; background: %(accent)s; }

QGroupBox { border: 1px solid %(border)s; border-radius: 12px; margin-top: 14px; padding: 12px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: %(muted)s;
    font-weight: 700; font-size: 11px; letter-spacing: 1px; }

QStatusBar { background: %(surface)s; border-top: 1px solid %(border)s; color: %(muted)s; }
QSplitter::handle { background: %(border)s; }
QSplitter::handle:hover { background: %(accent)s; }
QListWidget { background: %(surface_alt)s; border: 1px solid %(border)s; border-radius: 12px; }
QListWidget::item { padding: 6px 8px; border-radius: 6px; }
QListWidget::item:hover { background: %(surface_hi)s; }
QListWidget::item:selected { background: %(surface_hi)s; }
"""

GLYPHS = {
    "dashboard": "▤", "profile": "☰", "search": "⌕", "tasks": "◈", "applications": "✉",
    "insights": "∑", "settings": "⚙", "check": "✔", "cross": "✖", "info": "ℹ", "warn": "⚠",
    "refresh": "↻", "add": "＋", "open": "↗", "save": "✔", "send": "➤",
    "doc": "▣", "spark": "✦", "clock": "◔", "star": "★", "trash": "🗑",
}


@dataclass
class Theme:
    name: str = DEFAULT_THEME
    colors: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.colors = dict(PALETTES.get(self.name, PALETTES[DEFAULT_THEME]))

    def __getitem__(self, key: str) -> str:
        return self.colors.get(key, "#ffffff")

    def stylesheet(self) -> str:
        family = QApplication.font().family() or "Segoe UI"
        values = dict(self.colors)
        values["font"] = family.replace('"', "")
        return QSS % values


def apply_theme(app: QApplication, name: str = DEFAULT_THEME) -> Theme:
    theme = Theme(name)
    app.setStyleSheet(theme.stylesheet())
    app.setProperty("jautomatic_theme", theme.name)
    return theme


def tint(color: str, alpha: float) -> str:
    """``rgba()`` string for a translucent wash of ``color``.

    Qt style sheets read eight-digit hex as #AARRGGBB, so ``"#3ecf8e22"`` turns
    into a muddy olive instead of a soft green - always use rgba() for alpha.
    """
    value = QColor(color)
    alpha = max(0.0, min(1.0, float(alpha)))
    return f"rgba({value.red()}, {value.green()}, {value.blue()}, {alpha:.2f})"


def current_theme() -> Theme:
    app = QApplication.instance()
    name = ""
    if app is not None:
        name = str(app.property("jautomatic_theme") or "")
    return Theme(name or DEFAULT_THEME)


# --------------------------------------------------------------------------- #
# tiny factory helpers
# --------------------------------------------------------------------------- #
def label(text: str, role: str = "body", wrap: bool = False, parent: QWidget | None = None) -> QLabel:
    widget = QLabel(text, parent)
    widget.setObjectName({"muted": "Muted", "small": "Small", "title": "SectionTitle",
                          "h1": "H1", "page": "PageTitle"}.get(role, "Body"))
    widget.setWordWrap(wrap)
    if role == "muted":
        widget.setObjectName("Muted")
    return widget


def title_label(text: str, subtitle: str = "", parent: QWidget | None = None) -> QWidget:
    box = QWidget(parent)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    head = QLabel(text, box)
    head.setObjectName("PageTitle")
    layout.addWidget(head)
    if subtitle:
        sub = QLabel(subtitle, box)
        sub.setObjectName("PageSubtitle")
        layout.addWidget(sub)
    return box


def clear_layout(layout: QLayout | None) -> None:
    if layout is None:
        return
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def hline(parent: QWidget | None = None) -> QFrame:
    line = QFrame(parent)
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {current_theme()['border']}; border: none;")
    return line


def button(text: str, role: str = "default", tooltip: str = "",
           on_click=None) -> QPushButton:
    widget = QPushButton(text)
    widget.setObjectName({"primary": "Primary", "danger": "Danger", "ghost": "Ghost"}.get(role, ""))
    widget.setCursor(Qt.PointingHandCursor)
    if tooltip:
        widget.setToolTip(tooltip)
    if on_click is not None:
        widget.clicked.connect(on_click)
    return widget


def open_in_browser(url: str) -> bool:
    if not url:
        return False
    return QDesktopServices.openUrl(QUrl(url)) or webbrowser.open(url)


def open_in_file_manager(path: str | Path) -> bool:
    target = Path(path)
    if not target.exists():
        return False
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))


def open_path(path: str | Path) -> bool:
    """Open a document with the OS default application."""
    target = Path(path)
    if not target.exists():
        return False
    if target.suffix.lower() in (".docx", ".md", ".txt", ".pdf"):
        return QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
    return open_in_file_manager(target)


# --------------------------------------------------------------------------- #
# composite widgets
# --------------------------------------------------------------------------- #
class Card(QFrame):
    """Rounded surface with an optional heading and a right-aligned action row."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(10)
        self._root = root
        self.header = QHBoxLayout()
        self.header.setSpacing(8)
        if title:
            box = QVBoxLayout()
            box.setSpacing(1)
            head = QLabel(title)
            head.setObjectName("SectionTitle")
            box.addWidget(head)
            if subtitle:
                sub = QLabel(subtitle)
                sub.setObjectName("Small")
                sub.setWordWrap(True)
                box.addWidget(sub)
            self.header.addLayout(box)
        self.header.addStretch(1)
        root.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        root.addLayout(self.body)

    def add(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget)
        return widget

    def add_layout(self, layout: QLayout) -> QLayout:
        self.body.addLayout(layout)
        return layout

    def add_action(self, widget: QWidget) -> QWidget:
        self.header.addWidget(widget)
        return widget


class StatCard(Card):
    """Big-number tile used on the dashboard.

    ``color`` may be a palette token (``"info"``, ``"accent"``, …) or a literal
    hex string; tokens are re-resolved against the current palette on every
    ``set_value`` so switching themes recolours the tiles.
    """

    def __init__(self, caption: str, value: str = "0", hint: str = "",
                 color: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__("", "", parent)
        self.root_layout = self._root
        self.value_label = QLabel(value)
        self.value_label.setObjectName("StatValue")
        self._color = color
        self._apply_color()
        self.caption_label = QLabel(caption.upper())
        self.caption_label.setObjectName("StatLabel")
        self.hint_label = QLabel(hint)
        self.hint_label.setObjectName("Small")
        self.hint_label.setWordWrap(True)
        self.body.addWidget(self.value_label)
        self.body.addWidget(self.caption_label)
        self.body.addWidget(self.hint_label)
        self.setMinimumWidth(150)

    def _apply_color(self) -> None:
        color = self._color
        if color in PALETTES[current_theme().name]:
            color = current_theme()[color]
        if color:
            self.value_label.setStyleSheet(f"color: {color};")
        else:
            self.value_label.setStyleSheet("")

    def set_value(self, value: str, hint: str = "") -> None:
        self.value_label.setText(str(value))
        if hint:
            self.hint_label.setText(hint)
        self._apply_color()


class StatusChip(QLabel):
    """Coloured pill for an application status."""

    def __init__(self, status=None, parent: QWidget | None = None) -> None:
        super().__init__("", parent)
        self.setObjectName("Chip")
        self.setAlignment(Qt.AlignCenter)
        if status is not None:
            self.set_status(status)

    def set_status(self, status) -> None:
        color = getattr(status, "color", "#8b93a7")
        text = getattr(status, "label", str(status))
        self.setText(text)
        self.setStyleSheet(
            f"background: {tint(color, 0.16)}; color: {color}; "
            f"border: 1px solid {tint(color, 0.45)}; border-radius: 9px; "
            f"padding: 2px 9px; font-size: 11px; font-weight: 700;")


class ScoreBar(QWidget):
    """Thin horizontal bar visualising a 0-100 match score."""

    def __init__(self, score: int = 0, parent: QWidget | None = None, height: int = 8) -> None:
        super().__init__(parent)
        self._score = max(0, min(100, int(score)))
        self.setFixedHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_score(self, score: int) -> None:
        self._score = max(0, min(100, int(score)))
        self.update()

    @property
    def score(self) -> int:
        return self._score

    @staticmethod
    def score_color(score: int) -> str:
        if score >= 80:
            return current_theme()["success"]
        if score >= 65:
            return current_theme()["accent"]
        if score >= 45:
            return current_theme()["warning"]
        return current_theme()["muted"]

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        theme = current_theme()
        radius = self.height() / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme["surface_alt"]))
        painter.drawRoundedRect(self.rect(), radius, radius)
        width = int(self.width() * self._score / 100)
        if width > 0:
            painter.setBrush(QColor(self.score_color(self._score)))
            bar = self.rect().adjusted(0, 0, -(self.width() - width), 0)
            path = QPainterPath()
            path.addRoundedRect(bar, radius, radius)
            painter.drawPath(path)
        painter.end()


class Toast(QFrame):
    """Inline, auto-fading message strip (success / info / warning / error)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setVisible(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 7, 10, 7)
        layout.setSpacing(8)
        self.glyph = QLabel("ℹ")
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.close_button = button("✖", "ghost")
        self.close_button.setFixedWidth(28)
        self.close_button.clicked.connect(lambda: self.setVisible(False))
        layout.addWidget(self.glyph)
        layout.addWidget(self.message, 1)
        layout.addWidget(self.close_button)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.setVisible(False))

    def show_message(self, text: str, level: str = "info", timeout_ms: int = 6000) -> None:
        theme = current_theme()
        color = {"info": theme["info"], "success": theme["success"],
                 "warning": theme["warning"], "error": theme["danger"]}.get(level, theme["info"])
        glyph = {"info": "ℹ", "success": "✔", "warning": "⚠", "error": "✖"}.get(level, "ℹ")
        self.glyph.setText(glyph)
        self.message.setText(text)
        self.setStyleSheet(f"background: {tint(color, 0.14)}; border: 1px solid "
                           f"{tint(color, 0.45)}; border-radius: 8px;")
        self.glyph.setStyleSheet(f"color: {color}; font-weight: 700;")
        self.setVisible(True)
        self._timer.start(timeout_ms)


class MarkdownPreviewDialog(QDialog):
    """Shows a generated document (CV/letter/e-mail) with save + open actions."""

    def __init__(self, title: str, markdown: str, path: str | Path | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 640)
        self.path = Path(path) if path else None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        head = QHBoxLayout()
        label_widget = QLabel(title)
        label_widget.setObjectName("PageTitle")
        head.addWidget(label_widget)
        head.addStretch(1)
        if self.path:
            path_label = QLabel(str(self.path))
            path_label.setObjectName("Small")
            path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            head.addWidget(path_label)
        layout.addLayout(head)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setMarkdown(markdown)
        layout.addWidget(browser, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        if self.path:
            row.addWidget(button("Open file", "default", "Open with the default application",
                                 self._open))
        row.addWidget(button("Copy text", "default", "Copy to clipboard", self._copy))
        row.addWidget(button("Close", "primary", "", self.accept))
        layout.addLayout(row)
        self._markdown = markdown

    def _open(self) -> None:
        if self.path:
            open_path(self.path)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._markdown)


class EmptyState(QWidget):
    """Friendly placeholder for empty tables."""

    def __init__(self, glyph: str, headline: str, hint: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 30, 20, 30)
        layout.setSpacing(6)
        icon = QLabel(glyph)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(f"font-size: 30px; color: {current_theme()['muted']};")
        head = QLabel(headline)
        head.setObjectName("SectionTitle")
        head.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)
        layout.addWidget(head)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("Muted")
            hint_label.setAlignment(Qt.AlignCenter)
            hint_label.setWordWrap(True)
            layout.addWidget(hint_label)
        self.buttons = QHBoxLayout()
        self.buttons.addStretch(1)
        layout.addLayout(self.buttons)

    def add_button(self, widget: QWidget) -> QWidget:
        self.buttons.addWidget(widget)
        return widget


def mono_font(size: int = 11) -> QFont:
    font = QFont("Consolas")
    font.setStyleHint(QFont.Monospace)
    font.setPointSize(size)
    return font


__all__ = [
    "DEFAULT_THEME",
    "GLYPHS",
    "PALETTES",
    "Card",
    "EmptyState",
    "MarkdownPreviewDialog",
    "ScoreBar",
    "StatCard",
    "StatusChip",
    "Theme",
    "Toast",
    "apply_theme",
    "button",
    "clear_layout",
    "current_theme",
    "hline",
    "label",
    "mono_font",
    "open_in_browser",
    "open_in_file_manager",
    "open_path",
    "tint",
    "title_label",
]
