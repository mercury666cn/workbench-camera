from __future__ import annotations

from datetime import datetime
import time

import numpy as np
from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.capture.recorder import VideoRecorder, snapshot_path
from app.capture.transform import apply_view, unrotate_norm
from app.config import AppConfig
from app.device.adb_phone import OFFLINE_HINT, AdbPhone, PhoneStatus
from app.device.camera_stream import CameraError, CameraStream, save_jpeg
from app.device.tools_bootstrap import ToolsError, ensure_scrcpy
from app.export.docx_export import export_docx, export_txt
from app.ocr.batch_job import BatchJob, PageStatus, ScanPage
from app.ocr.lmstudio_client import LMStudioClient, LMStudioError
from app.ocr.merge import join_pages, semantic_merge
from app.scan.document import detect_document, overlay_quad
from app.ui.preview_widget import PreviewWidget
from app.ui.settings_dialog import SettingsDialog
from app.ui.styles import APP_QSS


class FrameBridge(QObject):
    frame_ready = Signal(object)
    camera_error = Signal(str)
    phone_status = Signal(object)
    mac_status = Signal(bool, str)
    tools_ready = Signal(object, object)
    tools_failed = Signal(str)
    tools_progress = Signal(str)
    ocr_page = Signal(object)
    ocr_done = Signal()
    ocr_failed = Signal(str)
    merge_done = Signal(str, str)


class Worker(QThread):
    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.error = ""

    def run(self) -> None:
        try:
            self._fn(*self._args, **self._kwargs)
        except Exception as exc:
            self.error = str(exc)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("工作台相机")
        self.resize(1180, 760)
        self.setStyleSheet(APP_QSS)

        self.config = AppConfig.load()
        self.bridge = FrameBridge()
        self.phone: AdbPhone | None = None
        self.stream: CameraStream | None = None
        self.recorder = VideoRecorder()
        self.job = BatchJob(self.config.output_path())
        self._workers: list[QThread] = []
        self._last_quad_frame: np.ndarray | None = None
        self._merged_cache = ""
        self._want_preview = bool(self.config.auto_preview)
        self._starting = False
        self._backoff = 1
        self._reconnect_at = 0.0
        self._auto_retry_blocked = False
        self._initial_probe_pending = True
        self._watch = QTimer(self)
        self._watch.setInterval(3000)
        self._watch.timeout.connect(self._on_watch)
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.timeout.connect(self._apply_camera_zoom)
        self._usb_offline = False

        self._build()
        self._bind()
        QTimer.singleShot(200, self._bootstrap)

    def _build(self) -> None:
        self.phone_status = QLabel("正在准备…")
        self.phone_status.setObjectName("statusWarn")
        self.mac_status = QLabel("LM Studio 未检测")
        self.mac_status.setObjectName("statusWarn")
        self.hint = QLabel("点预览画面哪里就对哪里。关预览会释放相机降温，控制服务静默待命。")
        self.hint.setObjectName("hint")

        title = QLabel("工作台相机")
        title.setObjectName("title")
        self.settings_btn = QPushButton("设置")
        self.refresh_btn = QPushButton("重新检测")

        header = QHBoxLayout()
        header.addWidget(title)
        header.addSpacing(16)
        header.addWidget(self.phone_status)
        header.addWidget(_dot())
        header.addWidget(self.mac_status)
        header.addStretch()
        header.addWidget(self.refresh_btn)
        header.addWidget(self.settings_btn)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._bench_tab(), "工作台")
        self.tabs.addTab(self._scan_tab(), "扫描")

        root = QVBoxLayout()
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
        root.addLayout(header)
        root.addWidget(self.hint)
        root.addLayout(self._view_bar())
        root.addWidget(self.tabs, 1)

        wrap = QWidget()
        wrap.setLayout(root)
        self.setCentralWidget(wrap)

    def _view_bar(self) -> QHBoxLayout:
        self.rotate_btn = QPushButton("旋转")
        self.refocus_btn = QPushButton("重新对焦")
        self.zoom_slider = QSlider(Qt.Orientation.Horizontal)
        self.zoom_slider.setRange(10, 40)
        self.zoom_slider.setValue(int(round(max(1.0, min(self.config.zoom, 4.0)) * 10)))
        self.zoom_slider.setFixedWidth(160)
        self.zoom_label = QLabel(f"{self._zoom():.1f}x")
        self.zoom_label.setObjectName("hint")
        self.angle_label = QLabel(f"{self.config.rotation % 360}°")
        self.angle_label.setObjectName("hint")

        bar = QHBoxLayout()
        bar.addWidget(self.rotate_btn)
        bar.addWidget(self.angle_label)
        bar.addSpacing(12)
        bar.addWidget(QLabel("相机变焦"))
        bar.addWidget(self.zoom_slider)
        bar.addWidget(self.zoom_label)
        bar.addSpacing(12)
        bar.addWidget(self.refocus_btn)
        bar.addStretch()
        return bar

    def _bench_tab(self) -> QWidget:
        self.bench_preview = PreviewWidget("插上手机后会自动出画。手机保持黑屏。")
        self.start_btn = QPushButton("开启预览")
        self.start_btn.setObjectName("primary")
        self.stop_btn = QPushButton("关闭预览")
        self.stop_btn.setEnabled(False)
        self.shot_btn = QPushButton("快速抓拍")
        self.shot_btn.setEnabled(False)
        self.rec_btn = QPushButton("开始录像")
        self.rec_btn.setEnabled(False)
        self.bench_log = QLabel("未开启")
        self.bench_log.setObjectName("hint")

        btns = QVBoxLayout()
        btns.addWidget(self.start_btn)
        btns.addWidget(self.stop_btn)
        btns.addWidget(self.shot_btn)
        btns.addWidget(self.rec_btn)
        btns.addStretch()
        btns.addWidget(self.bench_log)

        side = QWidget()
        side.setFixedWidth(220)
        side.setLayout(btns)

        row = QHBoxLayout()
        row.addWidget(self.bench_preview, 1)
        row.addWidget(side)
        tab = QWidget()
        tab.setLayout(row)
        return tab

    def _scan_tab(self) -> QWidget:
        self.scan_preview = PreviewWidget("开启预览后，把资料放进画面，再点「扫描本页」。")
        self.scan_btn = QPushButton("扫描本页")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.setEnabled(False)
        self.ocr_btn = QPushButton("开始识别")
        self.retry_btn = QPushButton("重试失败页")
        self.join_btn = QPushButton("直接拼接")
        self.merge_btn = QPushButton("语义整合")
        self.export_txt_btn = QPushButton("导出文本")
        self.export_docx_btn = QPushButton("导出 Word")
        for btn in (
            self.ocr_btn,
            self.retry_btn,
            self.join_btn,
            self.merge_btn,
            self.export_txt_btn,
            self.export_docx_btn,
        ):
            btn.setEnabled(False)

        self.page_list = QListWidget()
        self.page_text = QPlainTextEdit()
        self.page_text.setPlaceholderText("选中一页后可校对识别结果")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.scan_log = QLabel("还没有扫描页")
        self.scan_log.setObjectName("hint")

        actions = QVBoxLayout()
        for btn in (
            self.scan_btn,
            self.ocr_btn,
            self.retry_btn,
            self.join_btn,
            self.merge_btn,
            self.export_txt_btn,
            self.export_docx_btn,
        ):
            actions.addWidget(btn)
        actions.addWidget(self.progress)
        actions.addWidget(self.scan_log)
        actions.addStretch()
        action_wrap = QWidget()
        action_wrap.setFixedWidth(180)
        action_wrap.setLayout(actions)

        right = QVBoxLayout()
        right.addWidget(QLabel("已扫页"))
        right.addWidget(self.page_list, 1)
        right.addWidget(QLabel("本页文本"))
        right.addWidget(self.page_text, 2)
        right_wrap = QWidget()
        right_wrap.setLayout(right)
        right_wrap.setFixedWidth(340)

        row = QHBoxLayout()
        row.addWidget(self.scan_preview, 1)
        row.addWidget(action_wrap)
        row.addWidget(right_wrap)
        tab = QWidget()
        tab.setLayout(row)
        return tab

    def _bind(self) -> None:
        self.bridge.frame_ready.connect(self._on_frame)
        self.bridge.camera_error.connect(self._on_camera_error)
        self.bridge.phone_status.connect(self._on_phone_status)
        self.bridge.mac_status.connect(self._on_mac_status)
        self.bridge.tools_ready.connect(self._on_tools_ready)
        self.bridge.tools_failed.connect(self._on_tools_failed)
        self.bridge.tools_progress.connect(self._set_phone_text)
        self.bridge.ocr_page.connect(self._on_ocr_page)
        self.bridge.ocr_done.connect(self._on_ocr_done)
        self.bridge.ocr_failed.connect(self._alert)
        self.bridge.merge_done.connect(self._on_merge_done)

        self.start_btn.clicked.connect(self._manual_start)
        self.stop_btn.clicked.connect(self._manual_stop)
        self.rotate_btn.clicked.connect(self._rotate)
        self.refocus_btn.clicked.connect(self._refocus)
        self.bench_preview.tapped.connect(self._on_preview_tap)
        self.scan_preview.tapped.connect(self._on_preview_tap)
        self.zoom_slider.valueChanged.connect(self._on_zoom)
        self.shot_btn.clicked.connect(self._snapshot)
        self.rec_btn.clicked.connect(self._toggle_record)
        self.settings_btn.clicked.connect(self._open_settings)
        self.refresh_btn.clicked.connect(self._manual_refresh)
        self.scan_btn.clicked.connect(self._scan_page)
        self.ocr_btn.clicked.connect(lambda: self._run_ocr(False))
        self.retry_btn.clicked.connect(lambda: self._run_ocr(True))
        self.join_btn.clicked.connect(self._join_export_ready)
        self.merge_btn.clicked.connect(self._semantic_merge)
        self.export_txt_btn.clicked.connect(lambda: self._export("txt"))
        self.export_docx_btn.clicked.connect(lambda: self._export("docx"))
        self.page_list.currentRowChanged.connect(self._show_page_text)
        self.page_text.textChanged.connect(self._save_page_text)

    def _bootstrap(self) -> None:
        self._set_phone_text("正在准备 scrcpy / ADB…", "statusWarn")

        def work() -> None:
            try:
                scrcpy, adb = ensure_scrcpy(progress=self.bridge.tools_progress.emit)
                self.bridge.tools_ready.emit(scrcpy, adb)
            except ToolsError as exc:
                self.bridge.tools_failed.emit(str(exc))

        self._run_bg(work)

    def _on_tools_ready(self, scrcpy, adb) -> None:
        self.phone = AdbPhone(adb, scrcpy)
        self._initial_probe_pending = True
        self._watch.start()
        self._refresh_status(list_cameras=True)

    def _on_tools_failed(self, message: str) -> None:
        self._set_phone_text("工具未就绪", "statusBad")
        self._alert(message)

    def _refresh_status(self, list_cameras: bool = False) -> None:
        if self.phone is None:
            return

        def work() -> None:
            status = self.phone.quick_status()
            if status.offline:
                self.bridge.phone_status.emit(status)
                return
            if list_cameras and not self._is_previewing():
                status = self.phone.probe(list_cameras=True)
            self.bridge.phone_status.emit(status)
            client = self._client()
            ok, msg, names = client.health()
            if ok and names and not self.config.lmstudio_model:
                self.config.lmstudio_model = names[0]
                self.config.save()
            self.bridge.mac_status.emit(ok, msg)

        self._run_bg(work)

    def _on_phone_status(self, status: PhoneStatus) -> None:
        self._initial_probe_pending = False
        if status.offline:
            self._usb_offline = True
            self._set_phone_text(status.message or OFFLINE_HINT, "statusBad")
            self.bench_log.setText(status.message or OFFLINE_HINT)
            return
        if status.connected:
            was_offline = self._usb_offline
            self._usb_offline = False
            self._apply_camera_preset()
            self._set_phone_text(status.message or "手机已连接（静默）", "statusOk")
            if was_offline:
                self._backoff = 1
            if self._want_preview and not self._is_previewing():
                self._try_auto_start()
            return
        self._set_phone_text(status.message or "手机未连接", "statusBad")

    def _on_mac_status(self, ok: bool, message: str) -> None:
        self.mac_status.setText(message)
        self.mac_status.setObjectName("statusOk" if ok else "statusBad")
        self.mac_status.style().unpolish(self.mac_status)
        self.mac_status.style().polish(self.mac_status)

    def _manual_start(self) -> None:
        self._auto_retry_blocked = False
        self._want_preview = True
        self.config.auto_preview = True
        self.config.save()
        self._backoff = 1
        if not self._start_preview(silent=False):
            return

    def _manual_stop(self) -> None:
        self._want_preview = False
        self.config.auto_preview = False
        self.config.save()
        self._stop_preview(reset_ui=True)
        self.bench_log.setText("相机已释放 · 控制服务待命")

    def _start_preview(self, silent: bool = True) -> bool:
        if self.phone is None:
            if not silent:
                self._alert("工具还没准备好")
            return False
        if self._usb_offline:
            self._set_phone_text(OFFLINE_HINT, "statusBad")
            if not silent:
                self.bench_log.setText(OFFLINE_HINT)
            return False
        if self._starting or self._is_previewing():
            return True
        self._starting = True
        try:
            status = self.phone.quick_status()
            if status.offline:
                self._usb_offline = True
                self._set_phone_text(status.message or OFFLINE_HINT, "statusBad")
                self.bench_log.setText(status.message or OFFLINE_HINT)
                return False
            if status.connected:
                self._set_phone_text(status.message or "手机已连接（静默）", "statusOk")
            else:
                self._set_phone_text(status.message or "手机未连接", "statusBad")
            if not status.connected:
                if not silent:
                    self.bench_log.setText(status.message)
                return False
            camera_id = status.back_camera_id or "0"
            if self.stream is None:
                self.stream = CameraStream(self.phone, camera_id)
            else:
                self.stream.camera_id = camera_id
            self.stream.camera_size = self.config.camera_size
            self.stream.camera_fps = self.config.camera_fps
            self.stream.camera_zoom = self._zoom()
            self.stream.set_callbacks(
                on_frame=self.bridge.frame_ready.emit,
                on_error=self.bridge.camera_error.emit,
            )
            self.stream.start()
            self.stream.set_zoom(self._zoom())
        except CameraError as exc:
            self.stream = None
            message = str(exc)
            if "相机服务" in message or message.strip() == "Aborted":
                self._auto_retry_blocked = True
                self.bench_log.setText("相机服务启动失败，请点「重新检测」")
            if not silent:
                self._alert(message)
            else:
                if not self._auto_retry_blocked:
                    self.bench_log.setText("重连中…")
            return False
        finally:
            self._starting = False
        self._backoff = 1
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.shot_btn.setEnabled(True)
        self.rec_btn.setEnabled(True)
        self.scan_btn.setEnabled(True)
        self.bench_log.setText("预览中 · 点画面可对焦")
        return True

    def _stop_preview(self, reset_ui: bool = True) -> None:
        if self.recorder.recording:
            self._toggle_record()
        if self.stream:
            self.stream.stop()
        if not reset_ui:
            return
        self.bench_preview.reset()
        self.scan_preview.reset()
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.shot_btn.setEnabled(False)
        self.rec_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)
        self.rec_btn.setText("开始录像")

    def _is_previewing(self) -> bool:
        return bool(self.stream and self.stream.running)

    def _try_auto_start(self) -> None:
        if self._usb_offline or self._auto_retry_blocked or self._initial_probe_pending:
            return
        if not self._want_preview or self._is_previewing() or self._starting:
            return
        if time.time() < self._reconnect_at:
            return
        if self._start_preview(silent=True):
            return
        if self._usb_offline or self._auto_retry_blocked:
            return
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        if self._usb_offline:
            return
        self._reconnect_at = time.time() + self._backoff
        self.bench_log.setText(f"重连中（{self._backoff}s）…")
        QTimer.singleShot(int(self._backoff * 1000), self._try_auto_start)
        self._backoff = min(self._backoff * 2, 4)

    def _on_watch(self) -> None:
        if self.phone is None:
            return
        if self._usb_offline:
            return
        if self._want_preview and not self._is_previewing():
            self._try_auto_start()

    def _manual_refresh(self) -> None:
        self._auto_retry_blocked = False
        self._refresh_status(list_cameras=True)

    def _on_frame(self, frame: object) -> None:
        if not isinstance(frame, np.ndarray):
            return
        viewed = apply_view(frame, self.config.rotation)
        if self.recorder.recording:
            self.recorder.write(viewed)
        elif self.recorder.worker_error is not None:
            try:
                self.recorder.stop()
            except Exception as exc:
                self._reset_record_button()
                self._alert(str(exc))
        if self.tabs.currentIndex() == 1:
            quad = detect_document(viewed)
            self.scan_preview.show_frame(overlay_quad(viewed, quad))
        else:
            self.bench_preview.show_frame(viewed)
        self._last_quad_frame = viewed

    def _on_camera_error(self, message: str) -> None:
        self._stop_preview(reset_ui=not self._want_preview)
        if self.phone is not None:
            status = self.phone.quick_status()
            if status.offline:
                self._usb_offline = True
                self._set_phone_text(status.message or OFFLINE_HINT, "statusBad")
                self.bench_log.setText(status.message or OFFLINE_HINT)
                return
        if self._want_preview and not self._usb_offline:
            self._schedule_reconnect()
            return
        self._alert(message)

    def _rotate(self) -> None:
        self.config.rotation = (int(self.config.rotation) + 90) % 360
        self.config.save()
        self.angle_label.setText(f"{self.config.rotation}°")

    def _on_zoom(self, value: int) -> None:
        self.config.zoom = max(1.0, min(value / 10.0, 4.0))
        self.zoom_label.setText(f"{self.config.zoom:.1f}x")
        self.config.save()
        if self._is_previewing():
            self._zoom_timer.start(80)

    def _apply_camera_zoom(self) -> None:
        if not self.stream or self._usb_offline:
            return
        setter = getattr(self.stream, "set_zoom", None)
        if setter is None:
            return
        setter(self._zoom())
        self.bench_log.setText(f"相机变焦 {self._zoom():.1f}x")

    def _zoom(self) -> float:
        return max(1.0, min(float(self.config.zoom or 1.0), 4.0))

    def _on_preview_tap(self, nx: float, ny: float) -> None:
        if not self._is_previewing() or self.stream is None:
            return
        cam_x, cam_y = unrotate_norm(nx, ny, self.config.rotation)
        self.stream.tap_focus(cam_x, cam_y)
        self.bench_log.setText("正在对焦…")
        QTimer.singleShot(1600, lambda: self.bench_log.setText("预览中 · 点画面可对焦"))

    def _refocus(self) -> None:
        if self._usb_offline:
            self._alert(OFFLINE_HINT)
            return
        if not self._is_previewing() or self.stream is None:
            self._alert("请先开启预览")
            return
        self.stream.refocus()
        self.bench_preview.mark_focus(0.5, 0.5)
        self.scan_preview.mark_focus(0.5, 0.5)
        self.bench_log.setText("正在对焦…")
        QTimer.singleShot(1600, lambda: self.bench_log.setText("预览中 · 点画面可对焦"))

    def _snapshot(self) -> None:
        try:
            frame = self._require_frame()
            path = snapshot_path(self.config.output_path())
            save_jpeg(frame, path)
            self.bench_log.setText(f"已保存 {path.name}")
        except (CameraError, OSError) as exc:
            self._alert(str(exc))

    def _toggle_record(self) -> None:
        if not self.recorder.recording:
            try:
                frame = self._require_frame()
                h, w = frame.shape[:2]
                output_size = self._record_output_size((w, h))
                path = self.recorder.start(
                    self.config.recording_path(),
                    (w, h),
                    fps=self.config.recording_fps,
                    codec=self.config.recording_codec,
                    bitrate_mbps=self.config.recording_bitrate_mbps,
                    encoder_mode=self.config.recording_encoder,
                    output_size=output_size,
                )
                self.rec_btn.setText("停止录像")
                self.rec_btn.setObjectName("danger")
                self.rec_btn.style().unpolish(self.rec_btn)
                self.rec_btn.style().polish(self.rec_btn)
                target = output_size or (w, h)
                bitrate = (
                    f"{self.config.recording_bitrate_mbps}Mbps"
                    if self.config.recording_bitrate_mbps
                    else "自动码率"
                )
                self.bench_log.setText(
                    f"录像中 · {_resolution_label(target)} · {self.config.recording_fps}fps · "
                    f"{self.config.recording_codec.upper()} · {bitrate} · {self.recorder.actual_encoder}"
                )
            except Exception as exc:
                self._alert(str(exc))
            return
        try:
            path = self.recorder.stop()
        except Exception as exc:
            path = None
            self._alert(str(exc))
        self._reset_record_button()
        self.bench_log.setText(f"录像已保存 {path.name}" if path else "录像已停止")

    def _reset_record_button(self) -> None:
        self.rec_btn.setText("开始录像")
        self.rec_btn.setObjectName("")
        self.rec_btn.setStyleSheet("")
        self.rec_btn.style().unpolish(self.rec_btn)
        self.rec_btn.style().polish(self.rec_btn)

    def _record_output_size(self, input_size: tuple[int, int]) -> tuple[int, int] | None:
        configured = self.config.recording_size
        if configured == "original":
            return None
        try:
            width, height = (int(value) for value in configured.split("x", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"录像分辨率无效：{configured}") from exc
        input_width, input_height = input_size
        if width * height > input_width * input_height:
            raise ValueError("录像输出不能高于当前相机输入，请先在设置里提高相机分辨率")
        if input_height > input_width and width > height:
            width, height = height, width
        return width, height

    def _scan_page(self) -> None:
        try:
            frame = self._require_frame()
            if not self.job.pages:
                self.job = BatchJob(self.config.output_path())
            page = self.job.add_frame(frame, auto_warp=True)
            item = QListWidgetItem(f"第 {page.index} 页 · {page.status.value}")
            self.page_list.addItem(item)
            self.page_list.setCurrentRow(len(self.job.pages) - 1)
            self.ocr_btn.setEnabled(True)
            self.scan_log.setText(f"已加入第 {page.index} 页")
            self._refresh_export_buttons()
        except (CameraError, OSError, RuntimeError) as exc:
            self._alert(str(exc))

    def _run_ocr(self, only_failed: bool) -> None:
        if not self.job.pages:
            self._alert("还没有扫描页")
            return
        client = self._client()
        self.progress.setRange(0, len(self.job.pages))
        self.progress.setValue(sum(1 for p in self.job.pages if p.status == PageStatus.done))
        self.ocr_btn.setEnabled(False)
        self.retry_btn.setEnabled(False)
        self.scan_log.setText("正在识别，一页一次…")

        def work() -> None:
            try:
                self.job.run_ocr(
                    client,
                    max_side=self.config.ocr_max_side,
                    only_failed=only_failed,
                    on_page=self.bridge.ocr_page.emit,
                )
                self.bridge.ocr_done.emit()
            except Exception as exc:
                self.bridge.ocr_failed.emit(str(exc))
                self.bridge.ocr_done.emit()

        self._run_bg(work)

    def _on_ocr_page(self, page: ScanPage) -> None:
        done = sum(1 for p in self.job.pages if p.status in (PageStatus.done, PageStatus.error))
        self.progress.setValue(done)
        row = page.index - 1
        if 0 <= row < self.page_list.count():
            suffix = f" · {page.error}" if page.error else ""
            self.page_list.item(row).setText(f"第 {page.index} 页 · {page.status.value}{suffix}")
        if self.page_list.currentRow() == row:
            self.page_text.blockSignals(True)
            self.page_text.setPlainText(page.text)
            self.page_text.blockSignals(False)
        self.scan_log.setText(f"第 {page.index} 页 {page.status.value}")

    def _on_ocr_done(self) -> None:
        self.ocr_btn.setEnabled(True)
        self.retry_btn.setEnabled(any(p.status == PageStatus.error for p in self.job.pages))
        self._refresh_export_buttons()
        self.scan_log.setText("识别结束")

    def _show_page_text(self, row: int) -> None:
        if row < 0 or row >= len(self.job.pages):
            return
        self.page_text.blockSignals(True)
        self.page_text.setPlainText(self.job.pages[row].text)
        self.page_text.blockSignals(False)

    def _save_page_text(self) -> None:
        row = self.page_list.currentRow()
        if 0 <= row < len(self.job.pages):
            self.job.pages[row].text = self.page_text.toPlainText()

    def _join_export_ready(self) -> None:
        text = join_pages(self.job.texts())
        if not text:
            self._alert("没有已识别的文本")
            return
        self.page_text.setPlainText(text)
        self.scan_log.setText("已按页拼接，可继续导出")
        self._refresh_export_buttons()
        self._merged_cache = text

    def _semantic_merge(self) -> None:
        pages = self.job.texts()
        if not pages:
            self._alert("没有已识别的文本")
            return
        self.scan_log.setText("正在语义整合…")
        self.merge_btn.setEnabled(False)

        def work() -> None:
            try:
                text = semantic_merge(self._client(), pages)
                self.bridge.merge_done.emit(text, "")
            except LMStudioError as exc:
                self.bridge.merge_done.emit(join_pages(pages), f"{exc}\n已回退到直接拼接。")

        self._run_bg(work)

    def _on_merge_done(self, text: str, warning: str) -> None:
        self._merged_cache = text
        self.page_text.setPlainText(text)
        self.merge_btn.setEnabled(True)
        self._refresh_export_buttons()
        self.scan_log.setText("整合完成，可导出")
        if warning:
            self._alert(warning)

    def _export(self, kind: str) -> None:
        text = getattr(self, "_merged_cache", "") or join_pages(self.job.texts())
        if not text:
            self._alert("没有可导出的文本")
            return
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = self.job.job_dir
        try:
            if kind == "txt":
                path = export_txt(text, folder / f"文稿_{stamp}.txt")
            else:
                path = export_docx(text, folder / f"文稿_{stamp}.docx")
            self.scan_log.setText(f"已导出 {path.name}")
        except OSError as exc:
            self._alert(str(exc))

    def _open_settings(self) -> None:
        camera = self.phone.back_camera() if self.phone else None
        old_format = (self.config.camera_size, self.config.camera_fps)
        dialog = SettingsDialog(
            self.config,
            self,
            camera_sizes=camera.sizes if camera else None,
            camera_fps=camera.fps if camera else None,
        )
        if dialog.exec():
            self.config = dialog.apply()
            self.job.output_dir = self.config.output_path()
            new_format = (self.config.camera_size, self.config.camera_fps)
            if new_format != old_format and self.stream is not None:
                was_previewing = self._is_previewing()
                self.stream.shutdown()
                self.stream = None
                if was_previewing:
                    self.bench_log.setText("正在应用新的相机格式…")
                    QTimer.singleShot(150, lambda: self._start_preview(silent=False))
            self._refresh_status()

    def _apply_camera_preset(self) -> None:
        if self.phone is None:
            return
        camera = self.phone.back_camera()
        if camera is None or not camera.sizes:
            return
        sizes = sorted(camera.sizes, key=_size_pixels, reverse=True)
        if self.config.camera_preset == "max":
            size = "3840x2160" if "3840x2160" in sizes else sizes[0]
            fps = 30 if 30 in camera.fps else max(camera.fps or [24])
        elif self.config.camera_preset == "smooth":
            size = "1920x1080" if "1920x1080" in sizes else sizes[-1]
            fps = 60 if 60 in camera.fps else max(camera.fps or [30])
        else:
            return
        if (size, fps) != (self.config.camera_size, self.config.camera_fps):
            self.config.camera_size = size
            self.config.camera_fps = fps
            self.config.save()

    def _require_frame(self) -> np.ndarray:
        if not self.stream:
            raise CameraError("请先开启预览")
        return apply_view(self.stream.snapshot(), self.config.rotation)

    def _client(self) -> LMStudioClient:
        return LMStudioClient(
            self.config.lmstudio_base_url,
            model=self.config.lmstudio_model,
            timeout=self.config.ocr_timeout_sec,
        )

    def _refresh_export_buttons(self) -> None:
        has_text = bool(self.job.texts() or getattr(self, "_merged_cache", ""))
        self.join_btn.setEnabled(bool(self.job.texts()))
        self.merge_btn.setEnabled(bool(self.job.texts()))
        self.export_txt_btn.setEnabled(has_text)
        self.export_docx_btn.setEnabled(has_text)

    def _set_phone_text(self, text: str, kind: str = "statusWarn") -> None:
        self.phone_status.setText(text)
        self.phone_status.setObjectName(kind)
        self.phone_status.style().unpolish(self.phone_status)
        self.phone_status.style().polish(self.phone_status)

    def _alert(self, message: str) -> None:
        if not message:
            return
        QMessageBox.warning(self, "工作台相机", message)

    def _run_bg(self, fn) -> None:
        worker = Worker(fn)
        self._track(worker)
        worker.start()

    def _track(self, worker: QThread) -> None:
        self._workers.append(worker)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)

    def closeEvent(self, event) -> None:
        self._want_preview = False
        self._watch.stop()
        if self.stream:
            self.stream.shutdown()
            self.stream = None
        if self.phone is not None:
            try:
                self.phone.restore_after_preview()
            except Exception:
                pass
        if self.recorder.recording:
            self.recorder.stop()
        super().closeEvent(event)


def _dot() -> QLabel:
    label = QLabel("·")
    label.setObjectName("hint")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return label


def _size_pixels(size: str) -> int:
    try:
        width, height = (int(value) for value in size.split("x", 1))
        return width * height
    except (TypeError, ValueError):
        return 0


def _resolution_label(size: tuple[int, int]) -> str:
    pixels = size[0] * size[1]
    if pixels >= 3840 * 2160:
        return "4K"
    if pixels >= 1920 * 1080:
        return "1080p"
    if pixels >= 1280 * 720:
        return "720p"
    return f"{size[0]}×{size[1]}"
