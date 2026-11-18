"""One island per desktop: second launch pings the first."""
import os

from PySide2.QtCore import QObject, Signal
from PySide2.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    activated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._name = f"ukui-island-{os.getuid()}"
        self._server = None

    def acquire(self) -> bool:
        sock = QLocalSocket()
        sock.connectToServer(self._name)
        if sock.waitForConnected(200):
            sock.write(b"toggle")
            sock.flush()
            sock.waitForBytesWritten(200)
            sock.disconnectFromServer()
            return False
        QLocalServer.removeServer(self._name)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        return self._server.listen(self._name)

    def _on_connection(self):
        conn = self._server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(lambda: conn.readAll())
            conn.disconnected.connect(conn.deleteLater)
        self.activated.emit()
