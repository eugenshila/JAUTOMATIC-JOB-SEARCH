"""Insights tab: trends, conversion funnel, response times and market demand.

Everything here is computed from the local SQLite database (no network, no new
big dependencies): the funnel and weekly series are drawn with QPainter the
same way :mod:`theme` paints score bars, and the two tables ("time to response",
"skills the market asks for") are plain widgets.
"""
from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme as th


def _color(key: str) -> QColor:
    return QColor(th.current_theme()[key])


# --------------------------------------------------------------------------- #
# tiny chart widgets (QPainter, theme-aware)
# --------------------------------------------------------------------------- #
class FunnelChart(QWidget):
    """Downward funnel of tracked -> sent -> interview -> offer, with losses."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data: list[dict] = []
        self.setMinimumHeight(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, data: list[dict]) -> None:
        self.data = data
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        theme = th.current_theme()
        rows = [row for row in self.data if row.get("value", 0) > 0]
        if not rows:
            self._draw_empty(painter)
            painter.end()
            return

        max_value = max(r["value"] for r in rows)
        margin_left = 108
        margin_right = 14
        top = 6
        gap = 6
        total = self.height() - top - 8
        stage_h = (total - gap * (len(rows) - 1)) / len(rows)

        for index, row in enumerate(rows):
            y0 = top + index * (stage_h + gap)
            y1 = y0 + stage_h
            width_factor = row["value"] / max_value
            box_w = max(40, (self.width() - margin_left - margin_right) * width_factor)
            path = QPainterPath()
            # a gentle trapezoid: the next stage's width shares the top edge
            next_factor = (rows[index + 1]["value"] / max_value
                           if index + 1 < len(rows) else width_factor)
            top_w = box_w
            bottom_w = max(40, (self.width() - margin_left - margin_right) * next_factor)
            dx_top = (self.width() - margin_left - margin_right - top_w) / 2
            dx_bot = (self.width() - margin_left - margin_right - bottom_w) / 2
            path.moveTo(margin_left + dx_top + top_w / 2, y0)
            path.lineTo(margin_left + dx_top + top_w / 2, y0)
            path.lineTo(margin_left + dx_top + top_w, y0)
            path.lineTo(margin_left + dx_bot + bottom_w, y1)
            path.lineTo(margin_left + dx_bot, y1)
            path.lineTo(margin_left + dx_top, y0 + stage_h / 2)
            path.closeSubpath()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(row.get("color", theme["accent"])))
            painter.drawPath(path)

            painter.setPen(QColor(theme["text"]))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(12, y0 + 16, row["label"])
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor(theme["muted"]))
            painter.drawText(12, y0 + 32, f"{row['value']}")

            if index + 1 < len(rows):
                kept = rows[index + 1]["value"] / row["value"] if row["value"] else 0
                pct = f"−{round((1 - kept) * 100)}%"
                painter.setPen(QColor(theme["muted"]))
                painter.drawText(self.width() - 90, int(y1 + 4), pct)
        painter.end()

    def _draw_empty(self, painter: QPainter) -> None:
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(th.current_theme()["surface_alt"]))
        painter.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 10, 10)
        painter.setPen(QColor(th.current_theme()["muted"]))
        painter.drawText(self.rect(), Qt.AlignCenter, "No applications yet")


class WeeklyChart(QWidget):
    """Grouped bars: postings created / sent / responses per week (last 8 weeks)."""

    LEGEND: ClassVar[list[tuple[str, str]]] = [
        ("created", "Created"), ("sent", "Sent"), ("responded", "Responses"),
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data: list[dict] = []
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, data: list[dict]) -> None:
        self.data = data
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        theme = th.current_theme()
        if not self.data:
            painter.setPen(QColor(theme["muted"]))
            painter.drawText(self.rect(), Qt.AlignCenter, "No data yet")
            painter.end()
            return

        max_value = max(max(r.get("created", 0), r.get("sent", 0), r.get("responded", 0))
                        for r in self.data) or 1
        margin = {"left": 36, "right": 10, "top": 26, "bottom": 24}
        plot_w = self.width() - margin["left"] - margin["right"]
        plot_h = self.height() - margin["top"] - margin["bottom"]
        n = len(self.data)
        group_w = plot_w / n
        bar_w = group_w * 0.24
        colors = {"created": _color("muted"), "sent": _color("accent"),
                  "responded": _color("success")}

        # grid + y labels
        painter.setPen(QColor(theme["border"]))
        for step in range(5):
            fy = margin["top"] + plot_h * (1 - step / 4)
            painter.drawLine(margin["left"], int(fy), self.width() - margin["right"], int(fy))
        painter.setPen(QColor(theme["muted"]))
        painter.setFont(th.mono_font(9))
        for step in range(5):
            fy = margin["top"] + plot_h * (1 - step / 4)
            painter.drawText(2, int(fy) + 3, f"{round(max_value * step / 4)}")

        for index, week in enumerate(self.data):
            cx = margin["left"] + group_w * (index + 0.5)
            for offset, (key, _label) in enumerate(self.LEGEND):
                value = week.get(key, 0)
                h = plot_h * value / max_value
                x = cx + (offset - 1) * bar_w * 1.15 - bar_w / 2
                painter.setPen(Qt.NoPen)
                painter.setBrush(colors[key])
                painter.drawRoundedRect(int(x), int(margin["top"] + plot_h - h),
                                        int(bar_w), int(h), 2, 2)
            if index % 2 == 0 or index == n - 1:
                painter.setPen(QColor(theme["muted"]))
                painter.drawText(int(cx - 22), self.height() - 6, week.get("week", ""))

        # legend
        x = margin["left"]
        y = 12
        for key, label in self.LEGEND:
            painter.setPen(Qt.NoPen)
            painter.setBrush(colors[key])
            painter.drawRoundedRect(x, y, 10, 10, 2, 2)
            painter.setPen(QColor(theme["text"]))
            painter.setFont(painter.font())
            painter.drawText(x + 14, y + 10, label)
            x += 14 + painter.fontMetrics().horizontalAdvance(label) + 20
        painter.end()


class HistogramChart(QWidget):
    """Horizontal bars for the score buckets."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data: list[dict] = []
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_data(self, data: list[dict]) -> None:
        self.data = data
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        theme = th.current_theme()
        if not self.data:
            painter.setPen(QColor(theme["muted"]))
            painter.drawText(self.rect(), Qt.AlignCenter, "No scored applications yet")
            painter.end()
            return
        max_value = max((d.get("count", 0) for d in self.data), default=1) or 1
        label_w = 64
        row_h = (self.height() - 10) / len(self.data)
        for index, bucket in enumerate(self.data):
            y = 5 + index * row_h + (row_h - 16) / 2
            painter.setPen(QColor(theme["muted"]))
            painter.setFont(painter.font())
            painter.drawText(0, int(y + 12), bucket.get("label", ""))
            count = bucket.get("count", 0)
            bar_w = max(0, (self.width() - label_w - 36) * count / max_value)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme["accent"]))
            painter.drawRoundedRect(label_w, int(y), int(bar_w), 16, 8, 8)
            painter.setPen(QColor(theme["text"]))
            painter.drawText(label_w + int(bar_w) + 8, int(y + 12), str(count))
        painter.end()


# --------------------------------------------------------------------------- #
# the tab
# --------------------------------------------------------------------------- #
class AnalyticsTab(QWidget):
    page_title = "Insights"
    page_subtitle = "What the data says about your search — and the market"

    def __init__(self, ctx) -> None:
        super().__init__()
        self.ctx = ctx
        self.stat_cards: dict[str, th.StatCard] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 6, 12)
        layout.setSpacing(14)

        tiles = QGridLayout()
        tiles.setSpacing(12)
        specs = [
            ("response", "Response rate", "of sent applications", "info"),
            ("interview", "Interview rate", "of sent applications", "warning"),
            ("offer", "Offer rate", "of sent applications", "success"),
            ("reply", "Median reply", "days from sent to a response", "accent"),
        ]
        for column, (key, caption, hint, color) in enumerate(specs):
            card = th.StatCard(f"{caption} · {hint}", "—", "", color)
            self.stat_cards[key] = card
            tiles.addWidget(card, 0, column)
            tiles.setColumnStretch(column, 1)
        layout.addLayout(tiles)

        columns = QHBoxLayout()
        columns.setSpacing(14)
        layout.addLayout(columns)

        left = QVBoxLayout()
        left.setSpacing(14)
        columns.addLayout(left, 3)

        self.funnel_card = th.Card("Pipeline funnel",
                                   "How far applications got, and where they were lost")
        self.funnel = FunnelChart()
        self.funnel_card.add(self.funnel)
        left.addWidget(self.funnel_card)

        self.weekly_card = th.Card("Activity per week",
                                   "Postings created, applications sent and responses — last 8 weeks")
        self.weekly = WeeklyChart()
        self.weekly_card.add(self.weekly)
        left.addWidget(self.weekly_card)

        self.score_card = th.Card("Match-score distribution",
                                  "Where your tracked postings land against your profile")
        self.histogram = HistogramChart()
        self.score_card.add(self.histogram)
        left.addWidget(self.score_card)

        self.reply_card = th.Card("Time to response",
                                  "Days from sending to a reply, fastest first")
        self.reply_table = QTableWidget(0, 4)
        self.reply_table.setHorizontalHeaderLabels(["Role", "Company", "Days", "Outcome"])
        self.reply_table.verticalHeader().setVisible(False)
        self.reply_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.reply_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.reply_table.setAlternatingRowColors(True)
        self.reply_table.setMaximumHeight(280)
        header = self.reply_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.reply_card.add(self.reply_table)
        self.reply_hint = th.label("", "small", wrap=True)
        self.reply_card.add(self.reply_hint)
        left.addWidget(self.reply_card)
        left.addStretch(1)

        right = QVBoxLayout()
        right.setSpacing(14)
        columns.addLayout(right, 2)

        self.market_card = th.Card("Skills the market asks for",
                                   "Topic tags across your stored postings, most demanded first")
        self.market_table = QTableWidget(0, 3)
        self.market_table.setHorizontalHeaderLabels(["Skill", "Postings", "You"])
        self.market_table.verticalHeader().setVisible(False)
        self.market_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.market_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.market_table.setAlternatingRowColors(True)
        self.market_table.setMaximumHeight(360)
        mheader = self.market_table.horizontalHeader()
        mheader.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2):
            mheader.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.market_card.add(self.market_table)

        def run_refresh() -> None:
            self.ctx.pipeline.refresh_scores(self.ctx.profile)
            self.refresh()

        self.market_card.add_action(th.button("Re-score & refresh", "ghost",
                                              "Recompute scores before running the analysis",
                                              run_refresh))
        self.market_hint = th.label("", "small", wrap=True)
        self.market_card.add(self.market_hint)
        right.addWidget(self.market_card)

        self.source_card = th.Card("Postings by source")
        self.source_rows = QVBoxLayout()
        self.source_rows.setSpacing(4)
        self.source_card.add_layout(self.source_rows)
        right.addWidget(self.source_card)
        right.addStretch(1)

    # ------------------------------------------------------------- refresh #
    def refresh(self) -> None:
        data = self.ctx.pipeline.analytics(self.ctx.profile)
        rates = data["rates"]
        self.stat_cards["response"].set_value(f"{rates['response']:.1f}%")
        self.stat_cards["interview"].set_value(f"{rates['interview']:.1f}%")
        self.stat_cards["offer"].set_value(f"{rates['offer']:.1f}%")
        self.stat_cards["reply"].set_value(
            f"{rates['median_reply_days']}d" if rates["median_reply_days"] is not None else "—",
            (f"{rates['avg_reply_days']}d average" if rates["avg_reply_days"] is not None else
             "no responses yet"))

        theme = th.current_theme()
        colors = {"tracked": theme["info"], "sent": theme["accent"],
                  "interview": theme["warning"], "offer": theme["success"]}
        funnel = [dict(row, color=colors.get(row["label"].lower(), theme["accent"]))
                  for row in data["funnel"]]
        self.funnel.set_data(funnel)
        self.weekly.set_data(data["weekly"])
        self.histogram.set_data(data["score_buckets"])
        self._fill_replies(data["response_times"])
        self._fill_market(self.ctx.pipeline.market_intelligence(self.ctx.profile))
        self._fill_sources(data["by_source"])
        self.update()

    def _fill_replies(self, rows: list[tuple[str, str, int, str]]) -> None:
        self.reply_table.setRowCount(len(rows))
        for index, (title, company, days, outcome) in enumerate(rows):
            for column, value in enumerate((title, company, f"{days}", outcome)):
                item = QTableWidgetItem(str(value))
                if column == 2:
                    item.setTextAlignment(Qt.AlignCenter)
                if column == 3:
                    item.setForeground(QColor(
                        {"Interview": th.current_theme()["warning"],
                         "Offer": th.current_theme()["success"],
                         "Rejected": th.current_theme()["danger"]}.get(outcome, "#888888")))
                self.reply_table.setItem(index, column, item)
        if not rows:
            self.reply_hint.setText("No replies to anything you sent yet. Keep going — "
                                    "the first data point usually shows up in the first weeks.")
        else:
            self.reply_hint.setText(f"{len(rows)} reply/replies recorded.")

    def _fill_market(self, data: list[dict]) -> None:
        theme = th.current_theme()
        self.market_table.setRowCount(len(data))
        for index, row in enumerate(data):
            titles = "\n".join(f"· {t}" for t in row["titles"])
            skill = QTableWidgetItem(row["tag"])
            skill.setToolTip(titles)
            count = QTableWidgetItem(str(row["count"]))
            count.setTextAlignment(Qt.AlignCenter)
            have = "✓" if row["have"] else "✗"
            have_item = QTableWidgetItem(have)
            have_item.setTextAlignment(Qt.AlignCenter)
            have_item.setForeground(QColor(theme["success"] if row["have"] else theme["muted"]))
            have_item.setToolTip("Your profile already mentions this" if row["have"]
                                 else "Not in your profile — a learning gap in the market")
            self.market_table.setItem(index, 0, skill)
            self.market_table.setItem(index, 1, count)
            self.market_table.setItem(index, 2, have_item)
        count = len(data)
        gaps = sum(1 for row in data if not row["have"])
        self.market_hint.setText(
            f"{count} distinct skills across your postings · {gaps} not yet in your profile"
            if count else "Import some postings to see which skills the market asks for.")

    def _fill_sources(self, rows: list[dict]) -> None:
        th.clear_layout(self.source_rows)
        if not rows:
            self.source_rows.addWidget(th.label("Nothing stored yet.", "muted", wrap=True))
            return
        theme = th.current_theme()
        max_count = max(row["count"] for row in rows) or 1
        for row in rows:
            line = QHBoxLayout()
            label_widget = th.label(row["source"], "muted")
            label_widget.setFixedWidth(130)
            bar = QLabel("")
            bar.setFixedHeight(14)
            bar.setStyleSheet(
                f"border-radius: 4px; background: {theme['accent']};")
            bar.setFixedWidth(int(160 * row["count"] / max_count))
            count = th.label(str(row["count"]), "small")
            line.addWidget(label_widget)
            line.addWidget(bar, 1)
            line.addWidget(count)
            container = QWidget()
            container.setLayout(line)
            self.source_rows.addWidget(container)


__all__ = ["AnalyticsTab", "FunnelChart", "HistogramChart", "WeeklyChart"]