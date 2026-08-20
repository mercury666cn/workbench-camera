# Workbench Camera

[English](README.md) · [简体中文](README.zh-CN.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-2f6fed)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB)](https://www.python.org/)
[![Windows](https://img.shields.io/badge/os-Windows%2010%2B-0078D6)](https://github.com/mercury666cn/workbench-camera)
[![PySide6](https://img.shields.io/badge/PySide6-6.8.3-41CD52)](requirements.txt)

Turn any Android phone into a Windows desk and document camera. Live preview, real zoom, tap-to-focus, capture, record, and optional OCR — no app to install on the phone.

![Workbench Camera cover](docs/hero.png)

## Features

- Live rear-camera preview over USB — not a screen mirror
- Real camera zoom and tap-to-focus on the preview
- Snapshot, record, and multi-page scan
- Optional OCR through your own LM Studio endpoint

## Interface

Designed mockups of the two main tabs (not pixel-perfect screenshots).

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/ui-workbench.png" alt="Workbench tab mockup" />
      <br />
      <sub>Workbench — preview, zoom, tap to focus, capture</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/ui-scan.png" alt="Scan tab mockup" />
      <br />
      <sub>Scan — pages, recognize, export Word</sub>
    </td>
  </tr>
</table>

## Quick start

1. Enable **Developer options → USB debugging** on the phone. Plug it in and accept the RSA prompt if asked.
2. Double-click `run.bat`. The first launch creates a virtualenv, installs dependencies, and downloads [scrcpy](https://github.com/Genymobile/scrcpy) 4.1 (includes ADB).
3. Click **开启预览**. Click the picture to focus; drag the slider to zoom.

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m app
```

**Pin `PySide6==6.8.3`.** Newer wheels (for example 6.11) can fail to load on Windows 10.

Files are saved under `Documents\工作台相机` by default.

## Requirements

- Windows 10 or later
- Python 3.11 or newer
- An Android phone with USB debugging
- A USB cable that carries data (not charge-only)

## Usage

| Action | What it does |
| --- | --- |
| Click the preview | Focus on that spot (Workbench and Scan) |
| Refocus | Hunt the center again — does **not** restart the camera |
| Zoom slider | Camera zoom, applied live |
| Rotate | Rotate the view on the PC (clicks map back to the sensor) |
| Scan | Capture pages, then run OCR if LM Studio is set up |

### Optional OCR (LM Studio)

Preview, zoom, focus, capture, and record work without OCR.

1. Start LM Studio and load a vision-capable model.
2. Enable the local server (default `http://127.0.0.1:1234/v1`).
3. If the server is on another machine, bind it to the LAN and put that URL in **Settings**.

## How it works

The PC pushes a patched scrcpy 4.1 server over ADB (not installed as a phone app) and talks to Camera2 on the same session used for zoom.

```
Phone camera  --USB/ADB-->  patched scrcpy-server  -->  this Windows app
```

We keep the official scrcpy 4.1 protocol. After the official Windows zip is downloaded, the app restores `tools/vendor/scrcpy-server` so tap-to-focus stays available.

## Known limits

- Some Huawei devices drop USB (`offline`) if the screen is forced asleep or if you run `dumpsys media.camera` during preview. Unplug, wait a few seconds, plug back in. Do not spam reconnect.
- On Camera2 **LIMITED** hardware, continuous AF is weaker than the stock Camera app.
- This is not a phone-screen mirror and not IP Webcam.

## Acknowledgments

Camera transport is based on [scrcpy](https://github.com/Genymobile/scrcpy) by Genymobile (Apache-2.0). This project ships a small server patch for continuous AF and tap-to-focus.

## License

[Apache License 2.0](LICENSE)
