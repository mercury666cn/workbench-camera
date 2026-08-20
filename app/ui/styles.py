APP_QSS = """
QWidget {
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    font-size: 13px;
    color: #e8eaed;
    background: #16181d;
}
QMainWindow, QDialog {
    background: #16181d;
}
QLabel#title {
    font-size: 16px;
    font-weight: 600;
    color: #f3f4f6;
}
QLabel#hint {
    color: #9aa3b2;
    font-size: 12px;
}
QLabel#statusOk { color: #3dd68c; }
QLabel#statusWarn { color: #f5c542; }
QLabel#statusBad { color: #f07178; }
QFrame#panel {
    background: #22262e;
    border: 1px solid #2e3440;
    border-radius: 8px;
}
QPushButton {
    background: #2b313c;
    border: 1px solid #3a4150;
    border-radius: 6px;
    padding: 7px 12px;
    min-height: 18px;
}
QPushButton:hover { background: #343b48; }
QPushButton:pressed { background: #1f242c; }
QPushButton:disabled { color: #6b7280; background: #1c2027; }
QPushButton#primary {
    background: #2f6fed;
    border-color: #3d8bfd;
    font-weight: 600;
}
QPushButton#primary:hover { background: #3b7af0; }
QPushButton#danger {
    background: #8b2e36;
    border-color: #c94c57;
}
QPushButton#danger:hover { background: #a43842; }
QLineEdit, QComboBox, QPlainTextEdit, QListWidget {
    background: #1b1f26;
    border: 1px solid #343b48;
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: #2f6fed;
}
QPlainTextEdit { padding: 8px; }
QTabWidget::pane {
    border: 1px solid #2e3440;
    border-radius: 8px;
    top: -1px;
    background: #1b1f26;
}
QTabBar::tab {
    background: #22262e;
    border: 1px solid #2e3440;
    padding: 7px 16px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background: #2f6fed;
    border-color: #3d8bfd;
}
QListWidget::item { padding: 6px 8px; }
QListWidget::item:selected { background: #2f6fed; }
QProgressBar {
    border: 1px solid #343b48;
    border-radius: 5px;
    background: #1b1f26;
    text-align: center;
    height: 16px;
}
QProgressBar::chunk { background: #2f6fed; border-radius: 4px; }
"""
