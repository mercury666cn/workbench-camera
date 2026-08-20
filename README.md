# Workbench Camera

[English](README.md) · [简体中文](README.zh-CN.md)

Turn any Android phone into a Windows desk and document camera. Live preview, real camera zoom, tap-to-focus, capture, record, and optional OCR — no app to install on the phone.

The phone stays a dumb USB camera. You work on the computer.

## Features

- **Live preview** over USB (rear camera, not a screen mirror)
- **Real zoom** via Camera2 `CONTROL_ZOOM_RATIO` — not a digital crop on the PC
- **Tap to focus** on the preview; “Refocus” hunts the center without restarting the stream
- **Capture and record** to your Documents folder
- **Batch scan** for multi-page paper
- **Optional OCR** through your own [LM Studio](https://lmstudio.ai/) endpoint

## Requirements

- Windows 10 or later
- Python 3.11 or newer
- An Android phone with **USB debugging** enabled
- A USB cable that carries data (not charge-only)

**Pin `PySide6==6.8.3`.** Newer wheels (for example 6.11) can fail to load on Windows 10.

## Quick start

1. Enable **Developer options → USB debugging** on the phone. Plug it in and accept the RSA prompt if asked.
2. Double-click `run.bat`. The first launch creates a virtualenv, installs dependencies, and downloads [scrcpy](https://github.com/Genymobile/scrcpy) 4.1 (includes ADB).
3. Open **Preview**. Click the picture to focus; drag the slider to zoom.

Manual install:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m app
```

Files are saved under `Documents\工作台相机` by default.

## Usage

| Action | What it does |
| --- | --- |
| Click the preview | Focus on that spot (works on both Workbench and Scan views) |
| Refocus | Focus the center again — does **not** restart the camera |
| Zoom slider | Camera zoom, applied live |
| Rotate | Rotate the view on the PC (click coordinates are mapped back) |
| Scan | Capture pages, then run OCR if LM Studio is set up |

### Optional OCR (LM Studio)

OCR is optional. Preview, zoom, focus, capture, and record work without it.

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

- Some Huawei devices drop USB (`offline`) if the screen is forced asleep or if you run `dumpsys media.camera` during preview. If that happens: unplug, wait a few seconds, plug back in. Do not spam reconnect.
- On Camera2 **LIMITED** hardware, continuous AF is weaker than the stock Camera app.
- This is not a phone-screen mirror and not IP Webcam.

## Acknowledgments

Camera transport is based on [scrcpy](https://github.com/Genymobile/scrcpy) by Genymobile, licensed under Apache-2.0. This project ships a small server patch for continuous AF and tap-to-focus.

## License

[Apache License 2.0](LICENSE)
