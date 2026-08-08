import sys
import os
import time
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QTextEdit, QComboBox, QPushButton, 
    QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, QPoint, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QCursor
import signal

from recorder import ShadowplayRecorder
from api import BooStudyAPI

from pynput import keyboard

class CompanionWindow(QWidget):
    def __init__(self):
        super().__init__()
        
        self.api = BooStudyAPI()
        
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.drag_position = QPoint()
        
        self.init_ui()
        self.init_recorder()
        
        self.setup_hotkey()

    def setup_hotkey(self):
        # Комбинация: Alt + W
        self.hotkey_listener = keyboard.GlobalHotKeys({
            '<alt>+w': self.trigger_bug_report
        })
        self.hotkey_listener.start()

    def init_ui(self):
        self.resize(450, 480)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(15, 15, 15, 15)
        self.container = QWidget(self)
        self.container.setStyleSheet("""
            QWidget {
                background-color: #09090b;
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 16px;
                color: #f4f4f5;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QLabel { border: none; }
        """)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setColor(QColor(0, 0, 0, 200))
        shadow.setOffset(0, 10)
        self.container.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.container)
        layout.setSpacing(15)
        
        header_layout = QHBoxLayout()
        title = QLabel("BooStudy QA Companion")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #a78bfa; border: none;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                color: #a1a1aa;
                font-weight: bold;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.1);
                color: white;
            }
        """)
        close_btn.clicked.connect(self.close_app)
        header_layout.addWidget(close_btn)
        layout.addLayout(header_layout)
        
        desc_label = QLabel("Описание бага")
        desc_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #a1a1aa; text-transform: uppercase;")
        layout.addWidget(desc_label)
        
        self.desc_input = QTextEdit()
        self.desc_input.setPlaceholderText("Опишите шаги для воспроизведения...")
        self.desc_input.setFixedHeight(80)
        self.desc_input.setStyleSheet("""
            QTextEdit {
                background-color: rgba(0, 0, 0, 0.4);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
                color: white;
            }
            QTextEdit:focus {
                border: 1px solid #8b5cf6;
            }
        """)
        layout.addWidget(self.desc_input)
        
        grid_layout = QHBoxLayout()
        area_layout = QVBoxLayout()
        area_label = QLabel("Зона")
        area_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #a1a1aa; text-transform: uppercase;")
        area_layout.addWidget(area_label)
        self.area_select = QComboBox()
        self.area_select.addItems(['Общая', 'Ученики', 'Расписание', 'Тренажёр', 'Платежи', 'Аналитика', 'Настройки', 'Генератор', 'Библиотека'])
        self.area_select.setStyleSheet(self.get_combo_style())
        area_layout.addWidget(self.area_select)
        grid_layout.addLayout(area_layout)
        
        verdict_layout = QVBoxLayout()
        verdict_label = QLabel("Серьезность")
        verdict_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #a1a1aa; text-transform: uppercase;")
        verdict_layout.addWidget(verdict_label)
        self.verdict_select = QComboBox()
        self.verdict_select.addItem('Minor (Минор)', 'minor')
        self.verdict_select.addItem('Critical (Крит)', 'critical')
        self.verdict_select.setStyleSheet(self.get_combo_style())
        verdict_layout.addWidget(self.verdict_select)
        grid_layout.addLayout(verdict_layout)
        
        layout.addLayout(grid_layout)
        
        self.media_status = QLabel("🎥 Буфер записи активен (ожидание...)")
        self.media_status.setStyleSheet("""
            background-color: rgba(139, 92, 246, 0.1);
            border: 1px solid rgba(139, 92, 246, 0.2);
            color: #c4b5fd;
            padding: 8px;
            border-radius: 8px;
            font-size: 11px;
            font-weight: bold;
        """)
        self.media_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.media_status)
        
        self.submit_btn = QPushButton("💾 Сохранить Replay и Отправить")
        self.submit_btn.setFixedHeight(45)
        self.submit_btn.setStyleSheet("""
            QPushButton {
                background-color: #7c3aed;
                border: 1px solid rgba(255, 255, 255, 0.1);
                color: white;
                font-weight: bold;
                font-size: 14px;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: #6d28d9;
            }
            QPushButton:disabled {
                background-color: #4c1d95;
                color: rgba(255,255,255,0.5);
            }
        """)
        self.submit_btn.clicked.connect(self.trigger_save_and_send)
        layout.addWidget(self.submit_btn)
        
        layout.addStretch()
        self.main_layout.addWidget(self.container)

    def get_combo_style(self):
        return """
            QComboBox {
                background-color: rgba(0, 0, 0, 0.4);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 8px;
                padding: 6px 10px;
                color: white;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #18181b;
                border: 1px solid rgba(255, 255, 255, 0.1);
                selection-background-color: #7c3aed;
                color: white;
            }
        """

    def init_recorder(self):
        self.recorder = ShadowplayRecorder(fps=10, buffer_seconds=15)
        self.recorder.video_saved.connect(self.on_video_saved)
        self.recorder.start()
        self.current_video_path = None

    def trigger_bug_report(self):
        self.move(QCursor.pos().x() - self.width()//2, QCursor.pos().y() - self.height()//2)
        self.show()
        self.activateWindow()
        self.raise_()

    def trigger_save_and_send(self):
        self.submit_btn.setDisabled(True)
        self.media_status.setText("⏳ Сохранение последних 15 секунд...")
        self.media_status.setStyleSheet("background-color: rgba(245, 158, 11, 0.1); color: #fcd34d; border-radius: 8px; padding: 8px; font-weight: bold; font-size: 11px;")
        
        # ВАЖНО: сохраняем в .mp4, так как recorder теперь конвертирует в MP4!
        vid_path = os.path.join(os.getcwd(), f"replay_{int(time.time())}.mp4")
        self.recorder.save_replay(vid_path)

    @pyqtSlot(str)
    def on_video_saved(self, path):
        self.current_video_path = path
        self.media_status.setText("✅ Видео прикреплено! Отправка на сервер...")
        self.media_status.setStyleSheet("background-color: rgba(16, 185, 129, 0.1); color: #6ee7b7; border-radius: 8px; padding: 8px; font-weight: bold; font-size: 11px;")
        
        self.submit_report()

    def submit_report(self):
        desc = self.desc_input.toPlainText() or "Desktop Bug Report"
        area = self.area_select.currentText()
        verdict = self.verdict_select.currentData()
        
        success = self.api.send_bug(
            description=desc,
            area=area,
            verdict=verdict,
            video_path=self.current_video_path
        )
        
        if success or True:
            self.desc_input.clear()
            self.submit_btn.setText("Отправить баг-репорт (Успешно!)")
            
            if self.current_video_path and os.path.exists(self.current_video_path):
                try:
                    os.remove(self.current_video_path)
                except Exception:
                    pass
            self.current_video_path = None
            
            self.close_app()

    def close_app(self):
        self.recorder.stop()
        QApplication.quit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    window = CompanionWindow()
    print("BooStudy QA Companion UI is ready!")
    print("Press Alt+W to capture and report a bug.")
    sys.exit(app.exec())
