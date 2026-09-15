from __future__ import annotations

import json
import shutil
import sys
import tempfile
import math
from pathlib import Path

from PySide6.QtCore import (
    QEasingCurve,
    QProcess,
    QPropertyAnimation,
    QRectF,
    QSettings,
    Qt,
    QUrl,
    QTimer,
)
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QLinearGradient, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QTabWidget,
    QGraphicsOpacityEffect,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    DoubleSpinBox,
    FluentIcon,
    FluentWindow,
    LineEdit,
    PlainTextEdit,
    ProgressBar,
    PushButton,
    StrongBodyLabel,
    Theme,
    TransparentPushButton,
    setTheme,
)


class SpinnerButton(QPushButton):
    """标准按钮外观，加载时在文字左侧绘制清晰的白色旋转弧线。"""

    def __init__(self, text: str, icon=None, parent=None):
        super().__init__(text, parent)
        self._idle_icon = icon.icon() if icon is not None else QIcon()
        self.setIcon(self._idle_icon)
        self._spinning = False
        self._angle = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._advance)
        self.setFixedHeight(40)

    def _advance(self) -> None:
        self._angle = (self._angle + 10.0) % 360.0
        self.update()

    def set_spinning(self, spinning: bool) -> None:
        self._spinning = spinning
        if spinning:
            self._angle = 0.0
            self.setIcon(QIcon())
            self._timer.start()
        else:
            self._timer.stop()
            self._angle = 0.0
            self.setIcon(self._idle_icon)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._spinning:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 245), 2.4, Qt.SolidLine, Qt.RoundCap))
        spinner_rect = QRectF(12, (self.height() - 16) / 2, 16, 16)
        painter.drawArc(spinner_rect, int(self._angle * 16), int(245 * 16))


class GlassTrajectoryView(QWidget):
    """轨迹画布；用深色渐变、透明网格和高亮路径模拟玻璃质感。"""

    def __init__(self, axis_pair: tuple[int, int], parent=None):
        super().__init__(parent)
        self.axis_pair = axis_pair
        self.points: list[tuple[float, float, float]] = []
        self.setMinimumHeight(290)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def set_points(self, points: list[list[float]] | list[tuple[float, float, float]]) -> None:
        self.points = [tuple(float(value) for value in point) for point in points]
        self.update()

    def clear_points(self) -> None:
        self.points = []
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        gradient = QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, QColor(17, 25, 35, 246))
        gradient.setColorAt(0.55, QColor(22, 30, 42, 238))
        gradient.setColorAt(1.0, QColor(9, 14, 21, 250))
        painter.fillRect(self.rect(), gradient)

        margin = 32.0
        grid_pen = QPen(QColor(145, 170, 195, 22), 1)
        painter.setPen(grid_pen)
        for index in range(1, 10):
            x = int(self.width() * index / 10)
            y = int(self.height() * index / 10)
            painter.drawLine(x, 0, x, self.height())
            painter.drawLine(0, y, self.width(), y)

        if len(self.points) < 2:
            painter.setPen(QColor(185, 198, 214, 190))
            painter.drawText(self.rect(), Qt.AlignCenter, "导出完成后显示轨迹预览")
            return

        first_axis, second_axis = self.axis_pair
        values = [
            (point[first_axis], point[second_axis])
            for point in self.points
            if math.isfinite(point[first_axis]) and math.isfinite(point[second_axis])
        ]
        if len(values) < 2:
            painter.setPen(QColor(185, 198, 214, 190))
            painter.drawText(self.rect(), Qt.AlignCenter, "轨迹数据无效")
            return

        min_x = min(value[0] for value in values)
        max_x = max(value[0] for value in values)
        min_y = min(value[1] for value in values)
        max_y = max(value[1] for value in values)
        raw_span_x = max_x - min_x
        raw_span_y = max_y - min_y
        padding_x = max(raw_span_x * 0.045, 1e-6)
        padding_y = max(raw_span_y * 0.045, 1e-6)
        min_x -= padding_x
        max_x += padding_x
        min_y -= padding_y
        max_y += padding_y
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)
        usable_width = max(self.width() - margin * 2, 1.0)
        usable_height = max(self.height() - margin * 2, 1.0)
        scale = min(usable_width / span_x, usable_height / span_y)
        offset_x = (self.width() - span_x * scale) / 2.0 - min_x * scale
        offset_y = (self.height() - span_y * scale) / 2.0 + max_y * scale

        def map_point(value):
            x = offset_x + value[0] * scale
            y = offset_y - value[1] * scale
            return x, y

        axis_pen = QPen(QColor(190, 210, 230, 65), 1)
        painter.setPen(axis_pen)
        if min_x <= 0 <= max_x:
            x = margin + (0 - min_x) * scale
            painter.drawLine(int(x), int(margin), int(x), int(self.height() - margin))
        if min_y <= 0 <= max_y:
            y = self.height() - margin - (0 - min_y) * scale
            painter.drawLine(int(margin), int(y), int(self.width() - margin), int(y))

        mapped = [map_point(value) for value in values]
        # 只保留很窄的低透明度底线，避免路径出现明显荧光晕染。
        painter.setPen(QPen(QColor(56, 189, 248, 30), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for previous, current in zip(mapped, mapped[1:]):
            painter.drawLine(int(previous[0]), int(previous[1]), int(current[0]), int(current[1]))

        painter.setPen(QPen(QColor(117, 206, 244, 235), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for previous, current in zip(mapped, mapped[1:]):
            painter.drawLine(int(previous[0]), int(previous[1]), int(current[0]), int(current[1]))

        start = mapped[0]
        end = mapped[-1]
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(74, 222, 128)))
        painter.drawEllipse(int(start[0] - 5), int(start[1] - 5), 10, 10)
        painter.setBrush(QBrush(QColor(248, 113, 113)))
        painter.drawEllipse(int(end[0] - 5), int(end[1] - 5), 10, 10)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(3)
        layout.addWidget(StrongBodyLabel(title))
        layout.addWidget(CaptionLabel(subtitle))


class MainPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mainPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 26, 30, 28)
        root.setSpacing(16)

        root.addWidget(PageHeader("SolidWorksTrajectory", "连接当前 SolidWorks 会话，选择草图并导出轨迹"))

        document_card = CardWidget()
        document_layout = QVBoxLayout(document_card)
        document_layout.setContentsMargins(20, 18, 20, 18)
        document_layout.setSpacing(12)
        document_header = QHBoxLayout()
        document_header.setSpacing(14)
        document_heading = QVBoxLayout()
        document_heading.setSpacing(3)
        document_heading.addWidget(StrongBodyLabel("SolidWorks 会话"))
        document_heading.addWidget(CaptionLabel("当前打开的模型和可导出的草图"))
        document_header.addLayout(document_heading, 1)
        self.model_title = BodyLabel("-")
        self.model_title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.model_title.setMinimumWidth(180)
        self.model_title.setMaximumWidth(360)
        self.model_title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.model_title.setWordWrap(False)
        self.model_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.model_title.setToolTip("当前模型")
        document_header.addWidget(self.model_title)
        self.refresh_button = SpinnerButton("●  刷新 SolidWorks")
        self.refresh_button.setMinimumWidth(164)
        self.refresh_button.setToolTip("重新读取当前 SolidWorks 文档")
        document_header.addWidget(self.refresh_button)
        document_layout.addLayout(document_header)

        document_form = QFormLayout()
        document_form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        document_form.setFormAlignment(Qt.AlignTop)
        document_form.setHorizontalSpacing(18)
        document_form.setVerticalSpacing(8)
        self.model_path = CaptionLabel("-")
        self.model_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sketch_combo = ComboBox()
        self.sketch_combo.setEnabled(False)
        self.model_path.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        document_form.addRow(CaptionLabel("草图"), self.sketch_combo)
        document_form.addRow(CaptionLabel("路径"), self.model_path)
        document_layout.addLayout(document_form)
        root.addWidget(document_card)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        self.start_button = SpinnerButton("开始导出", FluentIcon.PLAY)
        self.start_button.setMinimumWidth(120)
        self.start_button.setStyleSheet(self._primary_button_style())
        self.refresh_button.setFont(self.start_button.font())
        self.cancel_button = TransparentPushButton(FluentIcon.CANCEL, "取消")
        self.cancel_button.setEnabled(False)
        self.open_button = PushButton(FluentIcon.FOLDER, "打开输出目录")
        action_row.addWidget(self.start_button)
        action_row.addWidget(self.cancel_button)
        action_row.addStretch(1)
        action_row.addWidget(self.open_button)
        root.addLayout(action_row)

        status_card = CardWidget()
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(20, 14, 20, 14)
        status_layout.setSpacing(8)
        status_header = QHBoxLayout()
        status_header.addWidget(StrongBodyLabel("导出状态"))
        status_header.addStretch(1)
        self.stage_label = CaptionLabel("等待操作")
        status_header.addWidget(self.stage_label)
        self.progress = ProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        status_layout.addLayout(status_header)
        status_layout.addWidget(self.progress)
        self.summary = CaptionLabel("尚未导出")
        self.summary.setWordWrap(True)
        status_layout.addWidget(self.summary)
        root.addWidget(status_card)

        preview_card = QFrame()
        preview_card.setObjectName("previewCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(8)
        preview_header = QHBoxLayout()
        preview_header.addWidget(StrongBodyLabel("轨迹预览"))
        preview_header.addStretch(1)
        preview_header.addWidget(CaptionLabel("XY / XZ / YZ"))
        preview_layout.addLayout(preview_header)
        self.preview_tabs = QTabWidget()
        self.preview_tabs.setDocumentMode(True)
        self.views = {
            "XY": GlassTrajectoryView((0, 1)),
            "XZ": GlassTrajectoryView((0, 2)),
            "YZ": GlassTrajectoryView((1, 2)),
        }
        for name, view in self.views.items():
            self.preview_tabs.addTab(view, name)
        preview_layout.addWidget(self.preview_tabs, 1)
        root.addWidget(preview_card, 1)

        self.setStyleSheet(
            """
            QWidget#mainPage { background: transparent; }
            QFrame#previewCard {
                background: rgba(255, 255, 255, 145);
                border: 1px solid rgba(255, 255, 255, 175);
                border-radius: 12px;
            }
            QTabWidget::pane {
                background: rgba(15, 22, 30, 225);
                border: 1px solid rgba(255, 255, 255, 35);
                border-radius: 10px;
                top: -1px;
            }
            QTabBar::tab {
                padding: 7px 15px;
                margin-right: 3px;
                border-radius: 7px 7px 0 0;
            }
            QTabBar::tab:selected {
                color: #007f8b;
                background: rgba(0, 164, 180, 32);
                border-bottom: 2px solid #00a4b4;
            }
            """
        )
        self._preview_effects: dict[QWidget, QGraphicsOpacityEffect] = {}
        for view in self.views.values():
            effect = QGraphicsOpacityEffect(view)
            effect.setOpacity(1.0)
            view.setGraphicsEffect(effect)
            self._preview_effects[view] = effect
        self._preview_animation: QPropertyAnimation | None = None
        self.preview_tabs.currentChanged.connect(self._animate_preview_switch)
        self._connection_state: bool | None = None
        self.set_connection_state(None)

    def set_connection_state(self, state: bool | None) -> None:
        """更新右上角连接按钮颜色、文案和图标。"""
        self._connection_state = state
        self.refresh_button.set_spinning(False)
        if state is True:
            self.refresh_button.setText("●  已连接")
            self.refresh_button.setStyleSheet(
                """
                QPushButton {
                    background: #e5f4e8; border: none; border-radius: 10px;
                    color: #176b3a; min-height: 40px; padding: 0 14px; font-size: 14px;
                }
                QPushButton:hover { background: #d8eedc; }
                QPushButton:pressed { background: #c9e5cf; }
                """
            )
        elif state is False:
            self.refresh_button.setText("●  刷新 SolidWorks")
            self.refresh_button.setStyleSheet(
                """
                QPushButton {
                    background: #fbe8e7; border: 1px solid #e0a4a0; border-radius: 10px;
                    color: #a4262c; min-height: 40px; padding: 0 14px; font-size: 14px;
                }
                QPushButton:hover { background: #f6d9d7; }
                QPushButton:pressed { background: #efc7c4; }
                """
            )
        else:
            self.refresh_button.setText("●  刷新 SolidWorks")
            self.refresh_button.setStyleSheet(
                """
                QPushButton {
                    background: #ffffff; border: 1px solid #d1d1d1; border-radius: 10px;
                    color: #242424; min-height: 40px; padding: 0 14px; font-size: 14px;
                }
                QPushButton:hover { background: #f5f5f5; }
                QPushButton:pressed { background: #ebebeb; }
                """
            )

    def set_refresh_busy(self, busy: bool) -> None:
        if busy:
            self.refresh_button.setText("连接中…")
            self.refresh_button.setStyleSheet(
                """
                QPushButton {
                    background: #2b78c5; border: 1px solid #2166a8; border-radius: 10px;
                    color: #ffffff; min-height: 40px; padding: 0 14px 0 36px;
                    text-align: left; font-size: 14px;
                }
                QPushButton:hover { background: #246caf; }
                """
            )
            self.refresh_button.set_spinning(True)
        else:
            self.set_connection_state(self._connection_state)

    def set_export_busy(self, busy: bool) -> None:
        if busy:
            self.start_button.setText("导出中…")
            self.start_button.setStyleSheet(self._primary_button_style(loading=True))
            self.start_button.set_spinning(True)
        else:
            self.start_button.set_spinning(False)
            self.start_button.setText("开始导出")
            self.start_button.setStyleSheet(self._primary_button_style())

    @staticmethod
    def _primary_button_style(loading: bool = False) -> str:
        if loading:
            return """
                QPushButton {
                    background: #00a4b4; border: 1px solid #008e9c; border-radius: 8px;
                    color: #ffffff; min-height: 40px; padding: 0 14px 0 36px;
                    text-align: left; font-size: 14px;
                }
                QPushButton:hover { background: #0095a4; }
                QPushButton:pressed { background: #00838f; }
            """
        return """
            QPushButton {
                background: #00a4b4; border: 1px solid #008e9c; border-radius: 8px;
                color: #ffffff; min-height: 40px; padding: 0 14px; font-size: 14px;
            }
            QPushButton:hover { background: #0095a4; }
            QPushButton:pressed { background: #00838f; }
        """

    def _animate_preview_switch(self, index: int) -> None:
        view = self.preview_tabs.widget(index)
        effect = self._preview_effects.get(view)
        if effect is None:
            return
        if self._preview_animation is not None:
            self._preview_animation.stop()
        effect.setOpacity(0.55)
        self._preview_animation = QPropertyAnimation(effect, b"opacity", self)
        self._preview_animation.setDuration(220)
        self._preview_animation.setStartValue(0.55)
        self._preview_animation.setEndValue(1.0)
        self._preview_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._preview_animation.start()


class ConfigPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("configPage")
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 26, 30, 28)
        root.setSpacing(16)
        root.addWidget(PageHeader("导出配置", "设置 CSV、metadata、采样和覆盖策略"))

        export_card = CardWidget()
        export_layout = QVBoxLayout(export_card)
        export_layout.setContentsMargins(22, 20, 22, 22)
        export_layout.setSpacing(14)
        export_layout.addWidget(StrongBodyLabel("输出与采样"))
        export_layout.addWidget(CaptionLabel("这些参数会在下一次导出时生效，并自动保存到本机设置"))

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(22)
        form.setVerticalSpacing(12)
        self.output_edit = LineEdit()
        output_button = PushButton(FluentIcon.FOLDER, "选择")
        self.output_row = QWidget()
        output_row_layout = QHBoxLayout(self.output_row)
        output_row_layout.setContentsMargins(0, 0, 0, 0)
        output_row_layout.setSpacing(8)
        output_row_layout.addWidget(self.output_edit, 1)
        output_row_layout.addWidget(output_button)
        self.metadata_edit = LineEdit()
        self.metadata_edit.setPlaceholderText("留空则自动生成同名 metadata.json")
        self.sample_spin = DoubleSpinBox()
        self.sample_spin.setRange(0.001, 10000.0)
        self.sample_spin.setDecimals(3)
        self.sample_spin.setSuffix(" mm")
        self.offset_check = CheckBox("启用表面偏置")
        self.offset_spin = DoubleSpinBox()
        self.offset_spin.setRange(0.0, 10000.0)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setSuffix(" mm")
        offset_row = QWidget()
        offset_layout = QHBoxLayout(offset_row)
        offset_layout.setContentsMargins(0, 0, 0, 0)
        offset_layout.setSpacing(12)
        offset_layout.addWidget(self.offset_check)
        offset_layout.addWidget(self.offset_spin)
        offset_layout.addStretch(1)
        self.overwrite_check = CheckBox("允许覆盖已有文件")
        form.addRow("CSV 输出", self.output_row)
        form.addRow("metadata 输出", self.metadata_edit)
        form.addRow("圆弧采样步长", self.sample_spin)
        form.addRow("表面偏置", offset_row)
        form.addRow("文件策略", self.overwrite_check)
        export_layout.addLayout(form)
        root.addWidget(export_card)

        advanced_card = CardWidget()
        advanced_layout = QVBoxLayout(advanced_card)
        advanced_layout.setContentsMargins(22, 20, 22, 20)
        advanced_layout.setSpacing(8)
        advanced_layout.addWidget(StrongBodyLabel("当前连接策略"))
        advanced_layout.addWidget(CaptionLabel("SolidWorks 版本和连接等待时间沿用当前已验证的默认值：2023 / 5 秒。"))
        root.addWidget(advanced_card)
        root.addStretch(1)

        output_button.clicked.connect(self.choose_output)

    def choose_output(self) -> None:
        current = self.output_edit.text().strip() or "trajectory.csv"
        path, _ = QFileDialog.getSaveFileName(self, "选择 CSV 输出文件", current, "CSV 文件 (*.csv)")
        if path:
            self.output_edit.setText(path)


class ConsolePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("consolePage")
        root = QVBoxLayout(self)
        root.setContentsMargins(30, 26, 30, 28)
        root.setSpacing(16)
        root.addWidget(PageHeader("命令行信息", "实时显示 SolidWorks 连接、导出进度、警告和错误"))

        card = CardWidget()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        toolbar = QHBoxLayout()
        toolbar.addWidget(StrongBodyLabel("运行日志"))
        toolbar.addStretch(1)
        self.clear_button = TransparentPushButton(FluentIcon.DELETE, "清空")
        self.copy_button = PushButton(FluentIcon.COPY, "复制")
        toolbar.addWidget(self.clear_button)
        toolbar.addWidget(self.copy_button)
        self.log = PlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1500)
        layout.addLayout(toolbar)
        layout.addWidget(self.log, 1)
        root.addWidget(card, 1)
        self.clear_button.clicked.connect(self.log.clear)
        self.copy_button.clicked.connect(self.log.copy)

    def append(self, message: str) -> None:
        if message:
            self.log.appendPlainText(message)


class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        # 保留 FluentWindow 的导航结构，同时关闭桌面 Mica 对离屏/打包环境的黑色回退。
        self.setMicaEffectEnabled(False)
        self.setWindowTitle("SolidWorksTrajectory")
        self.resize(1280, 860)
        self.setMinimumSize(1080, 720)
        self.settings = QSettings("Codex", "SolidWorksTrajectory")
        self.process: QProcess | None = None
        self.run_dir: Path | None = None
        self.stdout_buffer = ""
        self.last_result: dict = {}
        self.active_operation: str | None = None
        self.progress_animation: QPropertyAnimation | None = None

        self.main_page = MainPage()
        self.config_page = ConfigPage()
        self.console_page = ConsolePage()
        self.addSubInterface(self.main_page, FluentIcon.HOME, "主界面")
        self.addSubInterface(self.config_page, FluentIcon.SETTING, "配置")
        self.addSubInterface(self.console_page, FluentIcon.CODE, "命令行")

        self.main_page.refresh_button.clicked.connect(self.refresh_model)
        self.main_page.start_button.clicked.connect(self.start_export)
        self.main_page.cancel_button.clicked.connect(self.cancel_export)
        self.main_page.open_button.clicked.connect(self.open_output_folder)
        self._load_settings()

    def _load_settings(self) -> None:
        default_csv = Path.home() / "Documents" / "SolidWorksTrajectory" / "trajectory.csv"
        self.config_page.output_edit.setText(self.settings.value("output_csv", str(default_csv)))
        self.config_page.metadata_edit.setText(self.settings.value("metadata_path", ""))
        self.config_page.sample_spin.setValue(float(self.settings.value("sample_step_mm", 1.0)))
        self.config_page.offset_check.setChecked(self.settings.value("offset_enabled", True, type=bool))
        self.config_page.offset_spin.setValue(float(self.settings.value("surface_offset_mm", 0.05)))
        self.config_page.overwrite_check.setChecked(self.settings.value("overwrite", True, type=bool))

    def _save_settings(self) -> None:
        self.settings.setValue("output_csv", self.config_page.output_edit.text().strip())
        self.settings.setValue("metadata_path", self.config_page.metadata_edit.text().strip())
        self.settings.setValue("sample_step_mm", self.config_page.sample_spin.value())
        self.settings.setValue("offset_enabled", self.config_page.offset_check.isChecked())
        self.settings.setValue("surface_offset_mm", self.config_page.offset_spin.value())
        self.settings.setValue("overwrite", self.config_page.overwrite_check.isChecked())

    def append_log(self, message: str, update_stage: bool = True) -> None:
        self.console_page.append(message)
        if message and update_stage:
            self.main_page.stage_label.setText(message)

    def _set_progress(self, value: float, immediate: bool = False) -> None:
        target = max(0, min(100, round(float(value))))
        current = self.main_page.progress.value()
        if self.progress_animation is not None:
            self.progress_animation.stop()
        if immediate or target <= current:
            self.main_page.progress.setValue(target)
            return
        self.progress_animation = QPropertyAnimation(self.main_page.progress, b"value", self)
        self.progress_animation.setStartValue(current)
        self.progress_animation.setEndValue(target)
        self.progress_animation.setDuration(max(140, min(850, (target - current) * 14)))
        self.progress_animation.setEasingCurve(QEasingCurve.Linear)
        self.progress_animation.start()

    def _create_run_files(self) -> tuple[Path, Path]:
        self.run_dir = Path(tempfile.mkdtemp(prefix="solidworks-trajectory-"))
        config_path = self.run_dir / "config.json"
        cancel_path = self.run_dir / "cancel.flag"
        config = {
            "sketch_name": self.main_page.sketch_combo.currentData() or None,
            "output_csv": self.config_page.output_edit.text().strip(),
            "metadata_path": self.config_page.metadata_edit.text().strip() or None,
            "sample_step_mm": self.config_page.sample_spin.value(),
            "surface_offset_mm": self.config_page.offset_spin.value()
            if self.config_page.offset_check.isChecked()
            else None,
            "solidworks_version": 2023,
            "wait_seconds": 5.0,
            "overwrite": self.config_page.overwrite_check.isChecked(),
        }
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return config_path, cancel_path

    def _start_process(self, operation: str) -> None:
        if self.process and self.process.state() != QProcess.NotRunning:
            return
        self.active_operation = operation
        config_path, cancel_path = self._create_run_files()
        self.stdout_buffer = ""
        self.last_result = {}
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.SeparateChannels)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parent.parent))
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.process_finished)
        self.process.errorOccurred.connect(self.process_error)
        if getattr(sys, "frozen", False):
            program = sys.executable
            args = ["--worker", "--operation", operation, "--config", str(config_path), "--cancel-file", str(cancel_path)]
        else:
            program = sys.executable
            args = ["-m", "trajectory_export_app.worker", "--operation", operation, "--config", str(config_path), "--cancel-file", str(cancel_path)]
        self.process.start(program, args)
        self._set_running(True)

    def refresh_model(self) -> None:
        self.main_page.set_connection_state(None)
        self.append_log("正在读取 SolidWorks 当前文档…")
        self._start_process("inspect")

    def start_export(self) -> None:
        output = self.config_page.output_edit.text().strip()
        if not output:
            QMessageBox.warning(self, "参数不完整", "请选择 CSV 输出文件。")
            self.main_page.start_button.setEnabled(True)
            return
        self._save_settings()
        self._set_progress(0, immediate=True)
        self.main_page.summary.setText("正在导出…")
        self.append_log("开始导出。")
        self._start_process("export")

    def cancel_export(self) -> None:
        if not self.run_dir:
            return
        (self.run_dir / "cancel.flag").write_text("cancel", encoding="ascii")
        self.main_page.cancel_button.setEnabled(False)
        self.main_page.stage_label.setText("正在请求取消…")
        self.append_log("已请求取消，等待当前 SolidWorks 调用返回。")

    def read_stdout(self) -> None:
        if not self.process:
            return
        self.stdout_buffer += bytes(self.process.readAllStandardOutput()).decode("utf-8", errors="replace")
        while "\n" in self.stdout_buffer:
            line, self.stdout_buffer = self.stdout_buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                self.handle_event(json.loads(line))
            except json.JSONDecodeError:
                self.append_log(line)

    def read_stderr(self) -> None:
        if self.process:
            text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            if text:
                self.append_log(text)

    def handle_event(self, record: dict) -> None:
        event = record.get("event")
        if event in {"status", "log"}:
            self.append_log(record.get("message", ""))
        elif event == "progress":
            percent = record.get("percent")
            if percent is not None:
                self._set_progress(float(percent))
            self.main_page.stage_label.setText(record.get("message", "处理中"))
        elif event == "inspect":
            self.main_page.set_connection_state(True)
            self.main_page.model_title.setText(record.get("model_title", "-"))
            self.main_page.model_title.setToolTip(record.get("model_title", "当前模型"))
            self.main_page.model_path.setText(record.get("model_path", "-"))
            self.main_page.sketch_combo.clear()
            for sketch in record.get("sketches", []):
                label = f"{sketch['name']} ({sketch['segment_count']} 段)"
                self.main_page.sketch_combo.addItem(label, sketch["name"])
            self.main_page.sketch_combo.setEnabled(bool(record.get("sketches")))
            self.main_page.stage_label.setText("模型信息读取完成")
            self.append_log(f"已读取模型：{record.get('model_title', '-')}，草图 {len(record.get('sketches', []))} 个。")
        elif event == "result":
            self.last_result = record
            self._set_progress(100)
            self.main_page.stage_label.setText("导出完成")
            self.main_page.summary.setText(
                f"草图: {record.get('sketch_name', '-')}    "
                f"点数: {record.get('point_count', 0)}    "
                f"长度: {record.get('trajectory_length_mm', 0):.6f} mm    "
                f"闭合: {'是' if record.get('path_closed') else '否'}\n"
                f"CSV: {record.get('csv_path', '')}\n"
                f"metadata: {record.get('metadata_path', '')}\n"
                f"警告: {len(record.get('warnings', []))} 条"
            )
            points = record.get("preview_points_mm", [])
            for view in self.main_page.views.values():
                view.set_points(points)
            for warning in record.get("warnings", []):
                self.append_log(f"警告: {warning}", update_stage=False)
        elif event == "error":
            if self.active_operation == "inspect":
                self.main_page.set_connection_state(False)
            self.main_page.stage_label.setText(record.get("message", "导出失败"))
            self.append_log(f"错误: {record.get('message', '未知错误')}")
        elif event == "cancelled":
            self.main_page.stage_label.setText("已取消")
            self.append_log(record.get("message", "导出已取消"))

    def process_finished(self, exit_code: int, exit_status) -> None:
        del exit_status
        self.read_stdout()
        if exit_code != 0 and not self.last_result:
            self.append_log(f"Worker 已结束，退出码: {exit_code}")
        self._set_running(False)
        self.active_operation = None
        if self.run_dir:
            shutil.rmtree(self.run_dir, ignore_errors=True)
            self.run_dir = None

    def process_error(self, error) -> None:
        if self.active_operation == "inspect":
            self.main_page.set_connection_state(False)
        self.append_log(f"Worker 启动失败: {error}")
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.main_page.refresh_button.setEnabled(not running)
        self.main_page.start_button.setEnabled(not running)
        self.main_page.cancel_button.setEnabled(running)
        self.main_page.open_button.setEnabled(not running)
        self.config_page.setEnabled(not running)
        self.main_page.set_refresh_busy(running and self.active_operation == "inspect")
        self.main_page.set_export_busy(running and self.active_operation == "export")

    def open_output_folder(self) -> None:
        path = Path(self.config_page.output_edit.text().strip()).expanduser()
        folder = path.parent if path.name else path
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    def closeEvent(self, event) -> None:
        if self.process and self.process.state() != QProcess.NotRunning:
            self.cancel_export()
            self.process.waitForFinished(1500)
            if self.process.state() != QProcess.NotRunning:
                self.process.kill()
        if self.run_dir:
            shutil.rmtree(self.run_dir, ignore_errors=True)
        self._save_settings()
        event.accept()


def main(argv: list[str] | None = None) -> int:
    del argv
    app = QApplication(sys.argv)
    setTheme(Theme.AUTO)
    window = MainWindow()
    window.show()
    return app.exec()
