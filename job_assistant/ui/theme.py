"""Qt stylesheet for a calm, accessible desktop experience."""
DARK_STYLESHEET = """
* { font-family: "Segoe UI"; }
QMainWindow, QWidget#root { background: #0d1117; color: #e6edf3; }
QFrame#sidebar { background: #111827; border-right: 1px solid #243244; }
QLabel#brand { color: #ffffff; font-size: 18px; font-weight: 700; }
QLabel#brandSub { color: #91a4b8; font-size: 11px; }
QPushButton#navButton { color: #9fb0c2; background: transparent; border: 0; border-radius: 8px; text-align: left; padding: 11px 14px; font-size: 13px; }
QPushButton#navButton:hover { background: #1b2a3b; color: #ffffff; }
QPushButton#navButton[active="true"] { background: #1d4ed8; color: #ffffff; font-weight: 600; }
QLabel#pageTitle { color: #f8fafc; font-size: 25px; font-weight: 700; }
QLabel#pageSubtitle { color: #91a4b8; font-size: 13px; }
QFrame#card { background: #151f2e; border: 1px solid #25364b; border-radius: 12px; }
QLabel#cardLabel { color: #91a4b8; font-size: 12px; }
QLabel#cardValue { color: #f8fafc; font-size: 25px; font-weight: 700; }
QLabel#cardHint { color: #6ee7b7; font-size: 11px; }
QLabel#sectionTitle { color: #eaf2fb; font-size: 15px; font-weight: 650; }
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox { background: #0f1722; color: #e6edf3; border: 1px solid #33465e; border-radius: 7px; padding: 8px; selection-background-color: #2563eb; }
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus { border: 1px solid #60a5fa; }
QTextEdit, QPlainTextEdit { padding: 9px; }
QCheckBox { color: #dbe7f3; spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; }
QPushButton#primary { background: #2563eb; color: white; border: 0; border-radius: 7px; padding: 10px 17px; font-weight: 650; }
QPushButton#primary:hover { background: #3b82f6; }
QPushButton#secondary { background: #1b2a3b; color: #dbeafe; border: 1px solid #3c536e; border-radius: 7px; padding: 9px 15px; }
QPushButton#secondary:hover { background: #263b54; }
QPushButton#danger { background: #391c26; color: #fda4af; border: 1px solid #7f1d35; border-radius: 7px; padding: 9px 15px; }
QLabel#muted { color: #91a4b8; }
QLabel#success { color: #6ee7b7; }
QLabel#warning { color: #fbbf24; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #101722; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #33465e; border-radius: 5px; min-height: 30px; }
QFrame#statusBar { background: #111827; border-top: 1px solid #243244; }
QLabel#statusText { color: #91a4b8; font-size: 11px; }
"""

LIGHT_STYLESHEET = DARK_STYLESHEET.replace("#0d1117", "#f6f8fb").replace("#e6edf3", "#172033").replace("#111827", "#ffffff").replace("#243244", "#dbe3ed").replace("#ffffff; font-size: 18px", "#172033; font-size: 18px").replace("#151f2e", "#ffffff").replace("#25364b", "#dbe3ed").replace("#f8fafc", "#172033").replace("#0f1722", "#fbfcfe").replace("#33465e", "#b8c5d4").replace("#1b2a3b", "#eef4fb").replace("#dbe7f3", "#24334a").replace("#eaf2fb", "#172033").replace("#101722", "#eef2f7")
