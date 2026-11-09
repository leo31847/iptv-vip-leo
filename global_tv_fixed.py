import sys
import os
import json
import urllib.parse
import urllib.request
import queue
import threading
import ssl
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QFrame, QSplitter, QVBoxLayout,
    QWidget, QPushButton, QHBoxLayout, QLabel
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, QTimer, Qt
import vlc

# Resolucion dinamica y robusta de directorios
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

LOCAL_INDEX = os.path.join(APP_DIR, 'index.html')

if os.path.exists(LOCAL_INDEX):
    INDEX_HTML = LOCAL_INDEX
elif hasattr(sys, '_MEIPASS'):
    INDEX_HTML = os.path.join(sys._MEIPASS, 'index.html')
else:
    INDEX_HTML = os.path.join(APP_DIR, 'index.html')
FAVS_FILE = os.path.join(APP_DIR, 'favoritos.json')
LISTS_FILE = os.path.join(APP_DIR, 'listas.json')

vlc_queue = queue.Queue()

# Contexto SSL seguro y tolerante
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

class Handler(BaseHTTPRequestHandler):
    def _cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            with open(INDEX_HTML, 'rb') as f:
                self.wfile.write(f.read())
        elif self.path == '/favs':
            self.send_response(200)
            self._cors_headers()
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            if os.path.exists(FAVS_FILE):
                with open(FAVS_FILE, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b'[]')
        elif self.path == '/lists':
            self.send_response(200)
            self._cors_headers()
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.end_headers()
            if os.path.exists(LISTS_FILE):
                with open(LISTS_FILE, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b'[]')
        elif self.path in ('/master.m3u', '/lista.m3u'):
            self.send_response(200)
            self._cors_headers()
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            master_file = os.path.join(APP_DIR, 'LISTA_MAESTRA_LEO_VIP.m3u')
            if os.path.exists(master_file):
                with open(master_file, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b'#EXTM3U\n')
        elif self.path.startswith('/proxy?url='):
            target_url = urllib.parse.unquote(self.path.split('/proxy?url=')[1])
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
                }
                req = urllib.request.Request(target_url, headers=headers)
                with urllib.request.urlopen(req, timeout=10, context=ssl_context) as response:
                    content = response.read()
                self.send_response(200)
                self._cors_headers()
                self.send_header('Content-Type', 'text/plain; charset=utf-8')
                self.end_headers()
                self.wfile.write(content)
            except Exception as e:
                self.send_response(500)
                self._cors_headers()
                self.end_headers()
                self.wfile.write(str(e).encode('utf-8'))
        else:
            self.send_error(404)

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        if self.path == '/play':
            try:
                data = json.loads(post_data.decode('utf-8'))
                urls = data.get('urls', [])
                name = data.get('channel_name', data.get('name', 'Desconocido'))
                vlc_queue.put({'urls': urls, 'name': name})
                self.send_response(200)
                self._cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception as e:
                self.send_response(400)
                self._cors_headers()
                self.end_headers()
        elif self.path == '/favs':
            try:
                with open(FAVS_FILE, 'wb') as f:
                    f.write(post_data)
                self.send_response(200)
                self._cors_headers()
                self.end_headers()
            except Exception as e:
                self.send_response(500)
                self._cors_headers()
                self.end_headers()
        elif self.path == '/lists':
            try:
                with open(LISTS_FILE, 'wb') as f:
                    f.write(post_data)
                self.send_response(200)
                self._cors_headers()
                self.end_headers()
            except Exception as e:
                self.send_response(500)
                self._cors_headers()
                self.end_headers()
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        return

def run_server():
    server = ThreadingHTTPServer(('0.0.0.0', 9999), Handler)
    server.serve_forever()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('GLOBAL TV MAX V19 PRO')
        self.setMinimumSize(1200, 800)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(self.splitter)

        self.view = QWebEngineView()
        self.splitter.addWidget(self.view)

        self.right_panel = QWidget()
        self.right_layout = QVBoxLayout(self.right_panel)
        self.right_layout.setContentsMargins(0, 0, 0, 0)
        self.right_layout.setSpacing(0)

        self.tv_title = QLabel('Selecciona un canal para reproducir')
        self.tv_title.setStyleSheet('background: #0f0f13; color: white; padding: 10px; font-weight: bold; font-family: sans-serif;')
        self.right_layout.addWidget(self.tv_title)

        self.video_frame = QFrame()
        self.video_frame.setStyleSheet('background: black;')
        self.right_layout.addWidget(self.video_frame)

        self.controls = QWidget()
        self.controls.setStyleSheet('background: #1a1a2e;')
        self.controls_layout = QHBoxLayout(self.controls)
        self.controls_layout.setContentsMargins(10, 5, 10, 5)

        self.btn_play = QPushButton('▶ Pausa / Play')
        self.btn_play.setStyleSheet('background: #4e54c8; color: white; padding: 6px 12px; border-radius: 4px; font-weight: bold;')
        self.btn_play.clicked.connect(self.toggle_play)
        self.controls_layout.addWidget(self.btn_play)

        self.btn_fs = QPushButton('⛶ Pantalla Completa')
        self.btn_fs.setStyleSheet('background: #3a3f58; color: white; padding: 6px 12px; border-radius: 4px;')
        self.btn_fs.clicked.connect(self.toggle_fullscreen)
        self.controls_layout.addWidget(self.btn_fs)

        self.btn_pip = QPushButton('PiP')
        self.btn_pip.setStyleSheet('background: #3a3f58; color: white; padding: 6px 12px; border-radius: 4px;')
        self.btn_pip.clicked.connect(self.toggle_pip)
        self.controls_layout.addWidget(self.btn_pip)

        self.right_layout.addWidget(self.controls)
        self.splitter.addWidget(self.right_panel)
        self.splitter.setSizes([500, 780])

        self.pip_window = None

        # Argumentos exactos de V19 para maxima compatibilidad
        vlc_args = [
            '--network-caching=3000',
            '--no-keyboard-events',
            '--no-mouse-events'
        ]
        self.vlc_instance = vlc.Instance(*vlc_args)
        self.player = self.vlc_instance.media_player_new()
        self.player.set_hwnd(int(self.video_frame.winId()))

        # Control de concurrencia y cambio rapido de canales
        self.current_request_id = 0
        self.switch_lock = threading.Lock()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_queue)
        self.timer.start(100) # Chequeo mas agil (100ms)

        self.view.setUrl(QUrl('http://localhost:9999/'))
        self.current_urls = []
        self.is_fullscreen = False

    def check_queue(self):
        # PURGA DE COLA: Si el usuario hizo clic en varios canales rapidamente,
        # descartar peticiones viejas y procesar unicamente la ultima elegida
        latest_data = None
        while not vlc_queue.empty():
            try:
                latest_data = vlc_queue.get_nowait()
            except queue.Empty:
                break
        
        if latest_data:
            urls = latest_data.get('urls', [])
            name = latest_data.get('name', 'Canal')
            if urls:
                self.tv_title.setText(f'▶ Reproduciendo: {name}')
                self.current_urls = urls
                # Ejecutar cambio de canal asincrono no bloqueante
                self.play_url_async(urls[0])

    def play_url_async(self, url):
        # Generar un ID unico para esta peticion de reproduccion
        self.current_request_id += 1
        req_id = self.current_request_id

        def _worker():
            # Ejecutar stop() y set_media() en segundo plano para NUNCA congelar la GUI
            with self.switch_lock:
                try:
                    self.player.stop()
                except Exception:
                    pass
                
                # Si el usuario ya toco otro canal mientras este se detenia, abortar
                if req_id != self.current_request_id:
                    return

                media = self.vlc_instance.media_new(url)
                media.add_option(':network-caching=3000')
                self.player.set_media(media)

                if req_id != self.current_request_id:
                    return

                self.player.play()

        threading.Thread(target=_worker, daemon=True).start()

    def toggle_play(self):
        if self.player.is_playing():
            self.player.pause()
        else:
            self.player.play()

    def toggle_fullscreen(self):
        if not self.is_fullscreen:
            self.view.hide()
            self.tv_title.hide()
            self.controls.hide()
            self.showFullScreen()
            self.is_fullscreen = True
        else:
            self.view.show()
            self.tv_title.show()
            self.controls.show()
            self.showNormal()
            self.showMaximized()
            self.is_fullscreen = False

    def toggle_pip(self):
        if self.pip_window is None:
            self.pip_window = QWidget()
            self.pip_window.setWindowTitle('PiP - GLOBAL TV MAX')
            self.pip_window.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
            self.pip_window.resize(480, 270)
            pip_layout = QVBoxLayout(self.pip_window)
            pip_layout.setContentsMargins(0, 0, 0, 0)
            self.right_layout.removeWidget(self.video_frame)
            pip_layout.addWidget(self.video_frame)
            self.pip_window.show()
            self.btn_pip.setText('Restaurar')
        else:
            self.close_pip()

    def close_pip(self):
        if self.pip_window:
            self.pip_window.layout().removeWidget(self.video_frame)
            self.right_layout.insertWidget(1, self.video_frame)
            self.pip_window.close()
            self.pip_window = None
            self.btn_pip.setText('PiP')

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.is_fullscreen:
            self.toggle_fullscreen()
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_fullscreen()
        super().mouseDoubleClickEvent(event)

if __name__ == '__main__':
    if not os.path.exists(FAVS_FILE):
        try:
            with open(FAVS_FILE, 'w') as f:
                f.write('[]')
        except:
            pass
    if not os.path.exists(LISTS_FILE):
        try:
            with open(LISTS_FILE, 'w') as f:
                f.write('[]')
        except:
            pass

    threading.Thread(target=run_server, daemon=True).start()
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())
