from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit, 
                             QPushButton, QHBoxLayout, QFrame)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor, QPalette

class LoginDialog(QDialog):
    login_requested = Signal(str)

    def __init__(self, saved_email="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Comic Translate - Нэвтрэх")
        self.setFixedSize(400, 250)
        self.setWindowFlags(Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint)
        
        # Style
        self.setStyleSheet("""
            QDialog {
                background-color: #121212;
                color: #ffffff;
            }
            QLabel {
                color: #bbbbbb;
                font-size: 14px;
            }
            QLineEdit {
                background-color: #1e1e1e;
                border: 1px solid #333333;
                border-radius: 8px;
                padding: 10px;
                color: white;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #0078d4;
            }
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #1086e0;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
            QPushButton#cancelBtn {
                background-color: transparent;
                color: #888888;
            }
            QPushButton#cancelBtn:hover {
                color: #ffffff;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)

        # Title
        title_label = QLabel("Программ ашиглах эрх шалгах")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: white;")
        layout.addWidget(title_label)

        # Email Input
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Таны бүртгэлтэй И-мэйл")
        self.email_input.setText(saved_email)
        layout.addWidget(self.email_input)

        # Status Label
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("font-size: 12px; color: #ff4444;")
        layout.addWidget(self.status_label)

        # Buttons
        btn_layout = QHBoxLayout()
        
        self.cancel_btn = QPushButton("Гарах")
        self.cancel_btn.setObjectName("cancelBtn")
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        
        self.login_btn = QPushButton("Нэвтрэх")
        self.login_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.clicked.connect(self.handle_login)
        
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.login_btn)
        layout.addLayout(btn_layout)

    def handle_login(self):
        email = self.email_input.text().strip()
        if not email:
            self.status_label.setText("И-мэйлээ оруулна уу!")
            return
        
        self.status_label.setText("Шалгаж байна...")
        self.login_btn.setEnabled(False)
        self.login_requested.emit(email)

    def set_error(self, message):
        self.status_label.setText(message)
        self.login_btn.setEnabled(True)
