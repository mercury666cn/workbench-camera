# Workbench Camera

**Reuse an old Android phone as a Windows camera**

[English](README.md) · [简体中文](README.zh-CN.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-2f6fed)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB)](https://www.python.org/)
[![Windows](https://img.shields.io/badge/os-Windows%2010%2B-0078D6)](https://github.com/mercury666cn/workbench-camera)
[![PySide6](https://img.shields.io/badge/PySide6-6.8.3-41CD52)](requirements.txt)

That Android in the drawer still has a camera. Plug it into Windows with USB debugging — no app on the phone, no need to keep it as your daily driver. The computer runs the preview; the phone is just the lens.

![Workbench Camera cover](docs/hero.png)

## What it’s for

- **Desk camera** — watch a workbench, soldering, or crafts from above
- **Document camera** — point at paper, scan pages, optional OCR
- **Wired monitor** — leave it aimed at a room, doorway, or desk and watch (or record) on the PC

This is **old Android + USB = a live picture on your computer**. It is not a cloud PTZ cam: no motion alerts, no phone app for remote viewing, no 24/7 NVR kit.

## Features

### Camera

- Rear-camera live preview over USB — not a screen mirror
- Real zoom (the lens / camera zoom, not a PC crop)
- Tap the preview to focus; Refocus hunts the center without restarting
- Rotate the view on the PC
- Snapshot and record

### Scan and OCR

- Multi-page scan
- Optional [LM Studio](https://lmstudio.ai/) OCR
- Export text or Word

### Why an old phone

- Retired or unused Androids work if USB debugging still turns on
- The PC is in control; the phone stays a dumb lens
- No extra camera app to install or keep open on the phone

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
- An Android phone with USB debugging (a spare or old one is enough)
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
- This is not a phone-screen mirror, not IP Webcam, and not a cloud security camera.

## Acknowledgments

Camera transport is based on [scrcpy](https://github.com/Genymobile/scrcpy) by Genymobile (Apache-2.0). This project ships a small server patch for continuous AF and tap-to-focus.

## License

[Apache License 2.0](LICENSE)
