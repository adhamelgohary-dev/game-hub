"""Coordinate app instances with a profile lock and a local activation signal."""

from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep

from PySide6.QtCore import QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance:
    def __init__(self, data_root: Path, activate: Callable[[], None]) -> None:
        self._root = data_root.resolve()
        profile_key = sha256(str(self._root).casefold().encode("utf-8")).hexdigest()[:24]
        self._name = f"gamehub-{profile_key}"
        self._lock = QLockFile(str(self._root / "gamehub.lock"))
        self._lock.setStaleLockTime(0)
        self._server = QLocalServer()
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._accept_activation)
        self._activate = activate

    def claim_or_activate(self) -> bool:
        """Become primary, or wake the primary and return False."""
        self._root.mkdir(parents=True, exist_ok=True)
        if self._lock.tryLock(0):
            QLocalServer.removeServer(self._name)
            if self._server.listen(self._name):
                return True
            raise RuntimeError("Could not start the local activation service.")

        if self._lock.error() != QLockFile.LockError.LockFailedError:
            raise OSError("Could not lock the local GameRewind data folder.")

        # Another process may have the lock while starting up OR just releasing it on exit.
        deadline = monotonic() + 1.0
        while monotonic() < deadline:
            if self._lock.tryLock(0):
                QLocalServer.removeServer(self._name)
                if self._server.listen(self._name):
                    return True
                raise RuntimeError("Could not start the local activation service.")
            client = QLocalSocket()
            client.connectToServer(self._name)
            if client.waitForConnected(50):
                client.disconnectFromServer()
                return False
            sleep(0.025)
        raise RuntimeError("The running GameRewind instance did not respond.")

    def _accept_activation(self) -> None:
        while self._server.hasPendingConnections():
            client = self._server.nextPendingConnection()
            client.disconnectFromServer()
            client.deleteLater()
        self._activate()

    def close(self) -> None:
        self._server.close()
        if self._lock.isLocked():
            self._lock.unlock()
