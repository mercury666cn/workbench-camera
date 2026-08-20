from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.config import AppConfig


class SettingsDialog(QDialog):
    def __init__(
        self,
        config: AppConfig,
        parent=None,
        camera_sizes: list[str] | None = None,
        camera_fps: list[int] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(560)
        self.config = config
        self.camera_sizes = _sort_sizes(camera_sizes or [config.camera_size, "1920x1080"])
        self.camera_fps_values = sorted(set(camera_fps or [15, 24, 30]))
        self._camera_preset = config.camera_preset

        self.url_edit = QLineEdit(config.lmstudio_base_url)
        self.model_edit = QLineEdit(config.lmstudio_model)
        self.model_edit.setPlaceholderText("留空则使用当前已加载的第一个模型")
        self.output_edit = QLineEdit(config.output_dir)
        browse = QPushButton("选择…")
        browse.clicked.connect(lambda: self._browse(self.output_edit, "选择抓拍与扫描目录"))
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(browse)

        self.size_combo = QComboBox()
        for size in self.camera_sizes:
            self.size_combo.addItem(size.replace("x", " × "), size)
        _select_data(self.size_combo, config.camera_size)
        self.fps_combo = QComboBox()
        for fps in self.camera_fps_values:
            self.fps_combo.addItem(f"{fps} fps", fps)
        _select_data(self.fps_combo, config.camera_fps)
        best_btn = QPushButton("一键最高画质")
        smooth_btn = QPushButton("1080p 流畅")
        best_btn.clicked.connect(self._set_best)
        smooth_btn.clicked.connect(self._set_smooth)
        presets = QHBoxLayout()
        presets.addWidget(best_btn)
        presets.addWidget(smooth_btn)
        presets.addStretch()
        camera_form = QFormLayout()
        camera_form.addRow("预设", presets)
        camera_form.addRow("取流分辨率", self.size_combo)
        camera_form.addRow("取流帧率", self.fps_combo)
        camera_group = QGroupBox("相机")
        camera_group.setLayout(camera_form)

        self.recording_edit = QLineEdit(config.recording_dir)
        rec_browse = QPushButton("选择…")
        rec_browse.clicked.connect(lambda: self._browse(self.recording_edit, "选择录像目录"))
        rec_path_row = QHBoxLayout()
        rec_path_row.addWidget(self.recording_edit, 1)
        rec_path_row.addWidget(rec_browse)
        self.record_size_combo = QComboBox()
        self.record_fps_combo = QComboBox()
        self.codec_combo = QComboBox()
        self.codec_combo.addItem("H.264（兼容性好）", "h264")
        self.codec_combo.addItem("H.265（同画质更省空间）", "h265")
        _select_data(self.codec_combo, config.recording_codec)
        self.encoder_combo = QComboBox()
        self.encoder_combo.addItem("自动（硬件优先，软件回退）", "auto")
        self.encoder_combo.addItem("软件编码", "software")
        _select_data(self.encoder_combo, config.recording_encoder)
        self.bitrate_spin = QSpinBox()
        self.bitrate_spin.setRange(0, 80)
        self.bitrate_spin.setSingleStep(2)
        self.bitrate_spin.setSpecialValueText("自动")
        self.bitrate_spin.setSuffix(" Mbps")
        self.bitrate_spin.setValue(config.recording_bitrate_mbps)
        rec_form = QFormLayout()
        rec_form.addRow("保存目录", rec_path_row)
        rec_form.addRow("输出分辨率", self.record_size_combo)
        rec_form.addRow("输出帧率", self.record_fps_combo)
        rec_form.addRow("编码", self.codec_combo)
        rec_form.addRow("编码方式", self.encoder_combo)
        rec_form.addRow("码率", self.bitrate_spin)
        recording_group = QGroupBox("录像（MP4）")
        recording_group.setLayout(rec_form)

        self.ocr_size_combo = QComboBox()
        for label, value in (("2000（速度优先）", 2000), ("3000（书页推荐）", 3000), ("4096（小字增强）", 4096), ("原图", 0)):
            self.ocr_size_combo.addItem(label, value)
        _select_data(self.ocr_size_combo, config.ocr_max_side)
        general_form = QFormLayout()
        general_form.addRow("LM Studio 地址", self.url_edit)
        general_form.addRow("模型名", self.model_edit)
        general_form.addRow("抓拍/扫描目录", out_row)
        general_form.addRow("OCR 输入质量", self.ocr_size_combo)
        general_group = QGroupBox("识别与文件")
        general_group.setLayout(general_form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(camera_group)
        layout.addWidget(recording_group)
        layout.addWidget(general_group)
        layout.addWidget(buttons)

        self._refresh_record_sizes(config.recording_size)
        self._refresh_record_fps(config.recording_fps)
        self.size_combo.currentIndexChanged.connect(self._camera_changed)
        self.fps_combo.currentIndexChanged.connect(self._camera_changed)

    def _browse(self, target: QLineEdit, title: str) -> None:
        folder = QFileDialog.getExistingDirectory(self, title, target.text())
        if folder:
            target.setText(folder)

    def _camera_changed(self) -> None:
        self._camera_preset = "manual"
        self._refresh_record_sizes()
        self._refresh_record_fps()

    def _set_best(self) -> None:
        self._camera_preset = "max"
        preferred_size = "3840x2160" if "3840x2160" in self.camera_sizes else self.camera_sizes[0]
        _select_data(self.size_combo, preferred_size)
        preferred = 30 if 30 in self.camera_fps_values else max(self.camera_fps_values)
        _select_data(self.fps_combo, preferred)
        self._camera_preset = "max"

    def _set_smooth(self) -> None:
        self._camera_preset = "smooth"
        target = "1920x1080" if "1920x1080" in self.camera_sizes else self.camera_sizes[-1]
        _select_data(self.size_combo, target)
        preferred = 60 if 60 in self.camera_fps_values else max(self.camera_fps_values)
        _select_data(self.fps_combo, preferred)
        self._camera_preset = "smooth"

    def _refresh_record_sizes(self, selected: str | None = None) -> None:
        selected = selected or self.record_size_combo.currentData() or "original"
        camera_pixels = _pixels(self.size_combo.currentData() or self.config.camera_size)
        self.record_size_combo.clear()
        self.record_size_combo.addItem("原始（不缩放）", "original")
        for size in ("3840x2160", "1920x1080", "1280x720", "854x480"):
            if _pixels(size) <= camera_pixels:
                self.record_size_combo.addItem(size.replace("x", " × "), size)
        _select_data(self.record_size_combo, selected)

    def _refresh_record_fps(self, selected: int | None = None) -> None:
        selected = int(selected or self.record_fps_combo.currentData() or 24)
        camera_fps = int(self.fps_combo.currentData() or 24)
        self.record_fps_combo.clear()
        values = [fps for fps in (15, 20, 24, 25, 30, 60) if fps <= camera_fps]
        for fps in values or [camera_fps]:
            self.record_fps_combo.addItem(f"{fps} fps", fps)
        available = [self.record_fps_combo.itemData(index) for index in range(self.record_fps_combo.count())]
        _select_data(self.record_fps_combo, selected if selected in available else max(available))

    def apply(self) -> AppConfig:
        self.config.lmstudio_base_url = self.url_edit.text().strip()
        self.config.lmstudio_model = self.model_edit.text().strip()
        self.config.output_dir = self.output_edit.text().strip()
        self.config.camera_size = self.size_combo.currentData() or "1920x1080"
        self.config.camera_fps = int(self.fps_combo.currentData() or 24)
        self.config.camera_preset = self._camera_preset
        self.config.recording_dir = self.recording_edit.text().strip()
        self.config.recording_size = self.record_size_combo.currentData() or "original"
        self.config.recording_fps = int(self.record_fps_combo.currentData() or 24)
        self.config.recording_codec = self.codec_combo.currentData() or "h264"
        self.config.recording_encoder = self.encoder_combo.currentData() or "auto"
        self.config.recording_bitrate_mbps = self.bitrate_spin.value()
        self.config.ocr_max_side = int(self.ocr_size_combo.currentData() or 0)
        self.config.save()
        return self.config


def _pixels(size: str) -> int:
    try:
        width, height = (int(value) for value in size.lower().split("x", 1))
        return width * height
    except (TypeError, ValueError):
        return 0


def _sort_sizes(sizes: list[str]) -> list[str]:
    valid = {size.lower().replace("×", "x").replace(" ", "") for size in sizes if _pixels(size.lower().replace("×", "x").replace(" ", ""))}
    return sorted(valid, key=_pixels, reverse=True) or ["1920x1080"]


def _select_data(combo: QComboBox, value) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)
