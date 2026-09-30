import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QTranslator
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from tneoral.settings import APP_DIR
from tneoral.ui.main_window import MainWindow

SERVER_NAME = "TNeoRal-single-instance"


def resource(name):
    #в exe файлы распаковываются в sys._MEIPASS
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    return base / name


def setup_logs():
    APP_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=APP_DIR / "tneoral.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        encoding="utf-8",
    )
    logging.getLogger("t_tech").setLevel(logging.WARNING)  # SDK пишет каждый запрос


def load_russian(app):
    tr = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    if not Path(folder).exists():
        folder = str(resource("translations"))
    if tr.load("qtbase_ru", folder):
        app.installTranslator(tr)
    else:
        logging.warning("русский перевод Qt не найден в %s", folder)


def on_crash(exc_type, exc, tb):
    #под pythonw консоли нет без этого ошибка просто пропадёт
    logging.error("необработанная ошибка", exc_info=(exc_type, exc, tb))
    #окно только из главного потока иначе зависнет
    if QApplication.instance() and threading.current_thread() is threading.main_thread():
        QMessageBox.critical(None, "TNeoRal", f"Ошибка: {exc}\n\nПодробности в {APP_DIR / 'tneoral.log'}")


def already_running():
    #второй экземпляр следил бы за теми же стопами и мог продать дважды
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


def listen_for_second(win):
    server = QLocalServer(win)
    QLocalServer.removeServer(SERVER_NAME)  # мог остаться после падения
    server.listen(SERVER_NAME)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), win.tray.show_window()))
    return server


def main():
    setup_logs()
    sys.excepthook = on_crash
    app = QApplication(sys.argv)
    app.setApplicationName("TNeoRal")
    if already_running():
        return
    load_russian(app)
    app.setQuitOnLastWindowClosed(False)  # живём в трее
    app.setStyleSheet(resource("tneoral/ui/theme.qss").read_text(encoding="utf-8"))

    win = MainWindow()
    win._single = listen_for_second(win)
    win.show()
    win.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
