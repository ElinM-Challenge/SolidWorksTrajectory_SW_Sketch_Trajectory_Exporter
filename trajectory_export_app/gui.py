from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QProgressBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class TrajectoryView(QWidget):
    def __init__(self, axis_pair: tuple[int, int], parent=None):
        super().__init__(parent)
        self.axis_pair = axis_pair
        self.points: list[tuple[float, float, float]] = []
        self.setMinimumHeight(260)

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
        painter.fillRect(self.rect(), QColor("#101418"))
        if len(self.points) < 2:
            painter.setPen(QColor("#8b949e"))
            painter.drawText(self.rect(), Qt.AlignCenter, "导出完成后显示轨迹预览")
            return

        first_axis, second_axis = self.axis_pair
        values = [(point[first_axis], point[second_axis]) for point in self.points]
        min_x = min(value[0] for value in values)
        max_x = max(value[0] for value in values)
        min_y = min(value[1] for value in values)
        max_y = max(value[1] for value in values)
        span_x = max(max_x - min_x, 1e-9)
        span_y = max(max_y - min_y, 1e-9)
        margin = 28.0
        scale = min((self.width() - margin * 2) / span_x, (self.height() - margin * 2) / span_y)

        def map_point(value):
            x = margin + (value[0] - min_x) * scale
            y = self.height() - margin - (value[1] - min_y) * scale
            return x, y

        painter.setPen(QPen(QColor("#30363d"), 1))
        if min_x <= 0 <= max_x:
            x = margin + (0 - min_x) * scale
            painter.drawLine(int(x), int(margin), int(x), int(self.height() - margin))
        if min_y <= 0 <= max_y:
            y = self.height() - margin - (0 - min_y) * scale
            painter.drawLine(int(margin), int(y), int(self.width() - margin), int(y))

        painter.setPen(QPen(QColor("#58a6ff"), 2))
        previous = map_point(values[0])
        for value in values[1:]:
            current = map_point(value)
            painter.drawLine(int(previous[0]), int(previous[1]), int(current[0]), int(current[1]))
            previous = current

        start = map_point(values[0])
        end = map_point(values[-1])
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor("#3fb950")))
        painter.drawEllipse(int(start[0] - 4), int(start[1] - 4), 8, 8)
        painter.setBrush(QBrush(QColor("#f85149")))
        painter.drawEllipse(int(end[0] - 4), int(end[1] - 4), 8, 8)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SolidWorks 草图轨迹导出")
        self.resize(980, 720)
        self.settings = QSettings("Codex", "SolidWorksTrajectory")
        self.process: QProcess | None = None
        self.run_dir: Path | None = None
        self.stdout_buffer = ""
        self.last_result: dict = {}
        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)

        model_group = QGroupBox("当前 SolidWorks 文档")
        model_layout = QFormLayout(model_group)
        self.model_status = QLabel("未读取")
        self.model_title = QLabel("-")
        self.model_path = QLabel("-")
        self.model_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.sketch_combo = QComboBox()
        self.sketch_combo.setEnabled(False)
        model_layout.addRow("连接状态", self.model_status)
        model_layout.addRow("模型", self.model_title)
        model_layout.addRow("路径", self.model_path)
        model_layout.addRow("草图", self.sketch_combo)

        config_group = QGroupBox("导出参数")
        config_layout = QFormLayout(config_group)
        self.output_edit = QLineEdit()
        output_button = QPushButton("选择…")
        output_button.clicked.connect(self.choose_output)
        output_row = QWidget()
        output_row_layout = QHBoxLayout(output_row)
        output_row_layout.setContentsMargins(0, 0, 0, 0)
        output_row_layout.addWidget(self.output_edit)
        output_row_layout.addWidget(output_button)
        self.metadata_edit = QLineEdit()
        self.metadata_edit.setPlaceholderText("留空则自动生成同名 metadata.json")
        self.sample_spin = QDoubleSpinBox()
        self.sample_spin.setRange(0.001, 10000.0)
        self.sample_spin.setDecimals(3)
        self.sample_spin.setSuffix(" mm")
        self.offset_check = QCheckBox("启用表面偏置")
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(0.0, 10000.0)
        self.offset_spin.setDecimals(3)
        self.offset_spin.setSuffix(" mm")
        offset_row = QWidget()
        offset_layout = QHBoxLayout(offset_row)
        offset_layout.setContentsMargins(0, 0, 0, 0)
        offset_layout.addWidget(self.offset_check)
        offset_layout.addWidget(self.offset_spin)
        offset_layout.addStretch(1)
        self.overwrite_check = QCheckBox("允许覆盖已有文件")
        config_layout.addRow("CSV 输出", output_row)
        config_layout.addRow("metadata 输出", self.metadata_edit)
        config_layout.addRow("圆弧采样步长", self.sample_spin)
        config_layout.addRow("表面偏置", offset_row)
        config_layout.addRow("文件策略", self.overwrite_check)

        controls = QHBoxLayout()
        self.refresh_button = QPushButton("刷新 SolidWorks")
        self.refresh_button.clicked.connect(self.refresh_model)
        self.start_button = QPushButton("开始导出")
        self.start_button.clicked.connect(self.start_export)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.cancel_export)
        self.cancel_button.setEnabled(False)
        self.open_button = QPushButton("打开输出目录")
        self.open_button.clicked.connect(self.open_output_folder)
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)
        controls.addWidget(self.start_button)
        controls.addWidget(self.cancel_button)
        controls.addWidget(self.open_button)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.stage_label = QLabel("等待操作")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        self.summary = QLabel("尚未导出")
        self.summary.setWordWrap(True)

        preview_tabs = QTabWidget()
        self.views = {
            "XY": TrajectoryView((0, 1)),
            "XZ": TrajectoryView((0, 2)),
            "YZ": TrajectoryView((1, 2)),
        }
        for name, view in self.views.items():
            preview_tabs.addTab(view, name)

        root_layout.addWidget(model_group)
        root_layout.addWidget(config_group)
        root_layout.addLayout(controls)
        root_layout.addWidget(self.stage_label)
        root_layout.addWidget(self.progress)
        root_layout.addWidget(preview_tabs, 1)
        root_layout.addWidget(self.summary)
        root_layout.addWidget(self.log, 1)
        self.setCentralWidget(root)

    def _load_settings(self) -> None:
        default_csv = Path.home() / "Documents" / "SolidWorksTrajectory" / "trajectory.csv"
        self.output_edit.setText(self.settings.value("output_csv", str(default_csv)))
        self.metadata_edit.setText(self.settings.value("metadata_path", ""))
        self.sample_spin.setValue(float(self.settings.value("sample_step_mm", 1.0)))
        self.offset_check.setChecked(self.settings.value("offset_enabled", True, type=bool))
        self.offset_spin.setValue(float(self.settings.value("surface_offset_mm", 0.05)))
        self.overwrite_check.setChecked(self.settings.value("overwrite", True, type=bool))

    def _save_settings(self) -> None:
        self.settings.setValue("output_csv", self.output_edit.text().strip())
        self.settings.setValue("metadata_path", self.metadata_edit.text().strip())
        self.settings.setValue("sample_step_mm", self.sample_spin.value())
        self.settings.setValue("offset_enabled", self.offset_check.isChecked())
        self.settings.setValue("surface_offset_mm", self.offset_spin.value())
        self.settings.setValue("overwrite", self.overwrite_check.isChecked())

    def append_log(self, message: str) -> None:
        if message:
            self.log.appendPlainText(message)

    def choose_output(self) -> None:
        current = self.output_edit.text().strip() or "trajectory.csv"
        path, _ = QFileDialog.getSaveFileName(self, "选择 CSV 输出文件", current, "CSV 文件 (*.csv)")
        if path:
            self.output_edit.setText(path)

    def _create_run_files(self) -> tuple[Path, Path]:
        self.run_dir = Path(tempfile.mkdtemp(prefix="solidworks-trajectory-"))
        config_path = self.run_dir / "config.json"
        cancel_path = self.run_dir / "cancel.flag"
        config = {
            "sketch_name": self.sketch_combo.currentData() or None,
            "output_csv": self.output_edit.text().strip(),
            "metadata_path": self.metadata_edit.text().strip() or None,
            "sample_step_mm": self.sample_spin.value(),
            "surface_offset_mm": self.offset_spin.value() if self.offset_check.isChecked() else None,
            "solidworks_version": 2023,
            "wait_seconds": 5.0,
            "overwrite": self.overwrite_check.isChecked(),
        }
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return config_path, cancel_path

    def _start_process(self, operation: str) -> None:
        if self.process and self.process.state() != QProcess.NotRunning:
            return
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
        self.append_log("正在读取 SolidWorks 当前文档…")
        self._start_process("inspect")

    def start_export(self) -> None:
        output = self.output_edit.text().strip()
        if not output:
            QMessageBox.warning(self, "参数不完整", "请选择 CSV 输出文件。")
            return
        self._save_settings()
        self.progress.setValue(0)
        self.summary.setText("正在导出…")
        self.append_log("开始导出。")
        self._start_process("export")

    def cancel_export(self) -> None:
        if not self.run_dir:
            return
        (self.run_dir / "cancel.flag").write_text("cancel", encoding="ascii")
        self.cancel_button.setEnabled(False)
        self.stage_label.setText("正在请求取消…")
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
                self.progress.setValue(max(0, min(100, round(float(percent)))))
            self.stage_label.setText(record.get("message", "处理中"))
        elif event == "inspect":
            self.model_status.setText("已连接")
            self.model_title.setText(record.get("model_title", "-"))
            self.model_path.setText(record.get("model_path", "-"))
            self.sketch_combo.clear()
            for sketch in record.get("sketches", []):
                label = f"{sketch['name']} ({sketch['segment_count']} 段)"
                self.sketch_combo.addItem(label, sketch["name"])
            self.sketch_combo.setEnabled(bool(record.get("sketches")))
            self.stage_label.setText("模型信息读取完成")
        elif event == "result":
            self.last_result = record
            self.progress.setValue(100)
            self.stage_label.setText("导出完成")
            self.summary.setText(
                f"草图: {record.get('sketch_name', '-')}\n"
                f"点数: {record.get('point_count', 0)}    "
                f"长度: {record.get('trajectory_length_mm', 0):.6f} mm    "
                f"闭合: {'是' if record.get('path_closed') else '否'}\n"
                f"CSV: {record.get('csv_path', '')}\n"
                f"metadata: {record.get('metadata_path', '')}\n"
                f"警告: {len(record.get('warnings', []))} 条"
            )
            points = record.get("preview_points_mm", [])
            for view in self.views.values():
                view.set_points(points)
            for warning in record.get("warnings", []):
                self.append_log(f"警告: {warning}")
        elif event == "error":
            self.model_status.setText("错误")
            self.stage_label.setText(record.get("message", "导出失败"))
            self.append_log(f"错误: {record.get('message', '未知错误')}")
        elif event == "cancelled":
            self.stage_label.setText("已取消")
            self.append_log(record.get("message", "导出已取消"))

    def process_finished(self, exit_code: int, exit_status) -> None:
        del exit_status
        self.read_stdout()
        if exit_code != 0 and not self.last_result:
            self.append_log(f"Worker 已结束，退出码: {exit_code}")
        self._set_running(False)
        if self.run_dir:
            shutil.rmtree(self.run_dir, ignore_errors=True)
            self.run_dir = None

    def process_error(self, error) -> None:
        self.append_log(f"Worker 启动失败: {error}")
        self._set_running(False)

    def _set_running(self, running: bool) -> None:
        self.refresh_button.setEnabled(not running)
        self.start_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.open_button.setEnabled(not running)

    def open_output_folder(self) -> None:
        path = Path(self.output_edit.text().strip()).expanduser()
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
    window = MainWindow()
    window.show()
    return app.exec()
