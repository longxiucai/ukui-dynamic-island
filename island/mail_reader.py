"""Scrollable plain-text window for reading a full email."""
from PySide2.QtCore import Qt
from PySide2.QtGui import QFont
from PySide2.QtWidgets import (QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout)


class MailReader(QDialog):
    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.setWindowTitle("邮件全文")
        self.resize(620, 480)
        self.setMinimumSize(420, 300)

        layout = QVBoxLayout(self)
        sender = QLabel(item.get("sender", ""))
        sender.setWordWrap(True)
        font = sender.font()
        font.setBold(True)
        sender.setFont(font)
        subject = QLabel(item.get("subject", ""))
        subject.setWordWrap(True)
        subject.setTextInteractionFlags(Qt.TextSelectableByMouse)
        meta = QLabel(item.get("date", ""))
        meta.setStyleSheet("color: palette(mid);")

        body = QPlainTextEdit()
        body.setReadOnly(True)
        body.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        body.setFont(QFont(body.font().family(), 10))
        if item.get("body_oversize"):
            text = "（邮件较大，未加载正文；请在邮箱客户端查看）"
        else:
            text = item.get("body") or item.get("preview") or "（这封邮件没有正文）"
        if item.get("body_truncated") and not item.get("body_oversize"):
            text += "\n\n……（邮件过长，已截断）"
        body.setPlainText(text)

        close = QPushButton("关闭")
        close.clicked.connect(self.close)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        layout.addWidget(sender)
        layout.addWidget(subject)
        layout.addWidget(meta)
        layout.addWidget(body, 1)
        layout.addLayout(row)
