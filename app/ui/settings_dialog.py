from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.config import AppConfig


class SettingsDialog(QDialog):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(460)
        self.config = config

        self.url_edit = QLineEdit(config.lmstudio_base_url)
        self.model_edit = QLineEdit(config.lmstudio_model)
        self.model_edit.setPlaceholderText("留空则使用当前已加载的第一个模型")
        self.output_edit = QLineEdit(config.output_dir)
        self.size_edit = QLineEdit(config.camera_size)

        browse = QPushButton("选择…")
        browse.clicked.connect(self._browse)
        out_row = QHBoxLayout()
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(browse)

        form = QFormLayout()
        form.addRow("LM Studio 地址", self.url_edit)
        form.addRow("模型名", self.model_edit)
        form.addRow("保存目录", out_row)
        form.addRow("相机分辨率", self.size_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择保存目录", self.output_edit.text())
        if folder:
            self.output_edit.setText(folder)

    def apply(self) -> AppConfig:
        self.config.lmstudio_base_url = self.url_edit.text().strip()
        self.config.lmstudio_model = self.model_edit.text().strip()
        self.config.output_dir = self.output_edit.text().strip()
        self.config.camera_size = self.size_edit.text().strip() or "1920x1080"
        self.config.save()
        return self.config
