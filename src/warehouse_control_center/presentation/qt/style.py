"""Professional, restrained visual styling for the desktop client."""

APPLICATION_STYLESHEET = """
QWidget {
    color: #172033;
    font-family: "Segoe UI";
    font-size: 14px;
}
QMainWindow, QDialog, QWidget#contentRoot, QWidget#loginRoot {
    background: #f4f6f9;
}
QFrame#card {
    background: white;
    border: 1px solid #dfe4ec;
    border-radius: 10px;
}
QLabel#pageTitle {
    color: #101828;
    font-size: 26px;
    font-weight: 650;
}
QLabel#mutedText {
    color: #667085;
}
QLabel#fieldLabel {
    color: #344054;
    font-weight: 600;
}
QLineEdit, QComboBox {
    background: white;
    border: 1px solid #cfd6e1;
    border-radius: 6px;
    min-height: 38px;
    padding: 0 10px;
}
QLineEdit:focus, QComboBox:focus {
    border: 2px solid #2563eb;
}
QPushButton {
    background: #2563eb;
    color: white;
    border: none;
    border-radius: 6px;
    min-height: 38px;
    padding: 0 18px;
    font-weight: 600;
}
QPushButton:hover { background: #1d4ed8; }
QPushButton:pressed { background: #1e40af; }
QPushButton:disabled { background: #aab7ca; color: #eef2f7; }
QPushButton[secondary="true"] {
    background: #eef2f7;
    color: #344054;
    border: 1px solid #d0d5dd;
}
QPushButton[secondary="true"]:hover { background: #e4e9f1; }
QPushButton[danger="true"] { background: #b42318; }
QPushButton[danger="true"]:hover { background: #912018; }
QTableWidget {
    background: white;
    alternate-background-color: #f8fafc;
    border: 1px solid #dfe4ec;
    border-radius: 8px;
    gridline-color: #e8ecf2;
    selection-background-color: #dbeafe;
    selection-color: #172033;
}
QHeaderView::section {
    background: #eef2f7;
    color: #344054;
    border: none;
    border-bottom: 1px solid #d0d5dd;
    padding: 10px 8px;
    font-weight: 650;
}
QFrame#sidebar {
    background: #172033;
    border: none;
}
QFrame#sidebar QLabel { color: #e5eaf2; }
QFrame#sidebar QPushButton {
    background: transparent;
    color: #d7deea;
    border-radius: 6px;
    text-align: left;
    padding: 0 18px;
}
QFrame#sidebar QPushButton:hover { background: #253149; }
QFrame#sidebar QPushButton:checked { background: #2563eb; color: white; }
QFrame#statusBanner[status="error"] {
    background: #fef3f2;
    border: 1px solid #fecdca;
    border-radius: 6px;
}
QFrame#statusBanner[status="warning"] {
    background: #fffaeb;
    border: 1px solid #fedf89;
    border-radius: 6px;
}
QFrame#statusBanner[status="success"] {
    background: #ecfdf3;
    border: 1px solid #abefc6;
    border-radius: 6px;
}
"""
