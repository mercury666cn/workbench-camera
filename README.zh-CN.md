# 工作台相机

**把闲置的安卓旧手机，变成 Windows 摄像头**

[English](README.md) · [简体中文](README.zh-CN.md)

[![License](https://img.shields.io/badge/license-Apache--2.0-2f6fed)](LICENSE)
[![Version](https://img.shields.io/badge/version-1.1.0-2f6fed)](https://github.com/mercury666cn/workbench-camera)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB)](https://www.python.org/)
[![Windows](https://img.shields.io/badge/os-Windows%2010%2B-0078D6)](https://github.com/mercury666cn/workbench-camera)
[![PySide6](https://img.shields.io/badge/PySide6-6.8.3-41CD52)](requirements.txt)

抽屉里那部旧安卓，镜头往往还能用。打开 USB 调试插上电脑即可：手机不用装 App，也不用再当主力机。预览和操作都在电脑上，手机只当镜头。手机支持 4K 就用 4K，录像可选 H.264 / H.265。换一台新手机，授权一次 USB 调试就能自动部署。

![工作台相机封面](docs/hero.png)

## 1.1.0 更新内容

- **手机支持就上 4K** — 设置里只列出这台手机真实支持的分辨率和帧率；「最高画质」优先 `3840×2160`
- **录像参数可调** — 路径、输出分辨率、帧率、H.264 / H.265、码率；优先硬件编码，失败自动回退软件
- **关预览不再拆服务** — 相机关掉降温，点选对焦继续待命
- **换机更稳** — 不装 APK，补丁服务走 ADB 写入并校验；不再用华为容易掉线的 `adb push`
- **中文路径 OCR 修好了** — 扫描页能正常保存、读取；LM Studio 会自动用当前已加载的模型

## 适合做什么

- **工作台相机** — 俯拍桌面、焊接、手工
- **文档相机** — 对着纸面拍、连扫，可选识别
- **有线监控** — 对着房间、门口或桌面，在电脑上看画面，也能录像

这就是 **旧安卓 + USB = 电脑上的实时画面**。它不是云台网络摄像头：没有移动侦测推送、没有远程看的手机 App、没有 24 小时无人值守套件。

## 功能

### 镜头

- USB 后置实时预览，不是镜像手机桌面
- 真变焦（相机变焦，不是电脑裁中间放大）
- 点预览哪里就对哪里；「重新对焦」不关相机
- 按手机真实支持的格式选分辨率，支持时可选 4K
- 关预览会释放相机，控制服务继续待命
- 电脑上旋转画面
- 抓拍；录像支持 H.264 / H.265（硬件优先，软件回退）

### 扫描与识别

- 多页连扫
- 可选接到 [LM Studio](https://lmstudio.ai/) 做 OCR
- 导出文本 / Word

### 为什么用旧手机

- 换下来或闲置的安卓，只要还能开 USB 调试就能用
- 电脑全控，手机当哑巴镜头
- 不用在手机上再装、再开一个相机 App

## 界面

下面是按软件风格做的示意，不是像素级截图。

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/ui-workbench.png" alt="工作台页示意" />
      <br />
      <sub>工作台 — 预览、变焦、点选对焦、抓拍</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/ui-scan.png" alt="扫描页示意" />
      <br />
      <sub>扫描 — 分页、识别、导出 Word</sub>
    </td>
  </tr>
</table>

## 快速开始

1. 手机打开 **开发者选项 → USB 调试**，插上电脑，如有提示就允许这台电脑调试。
2. 双击 `run.bat`。第一次会建虚拟环境、装依赖，并下载 [scrcpy](https://github.com/Genymobile/scrcpy) 4.1（自带 ADB）。
3. 点 **开启预览**。点画面可以对焦，拖拉条可以变焦。

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m app
```

**PySide6 必须锁 `6.8.3`。** 更新的版本（例如 6.11）在 Windows 10 上可能 DLL 加载失败。

文件默认保存在 `文档\工作台相机`。

## 环境

- Windows 10 或更新
- Python 3.11 或更新
- 安卓手机，打开 USB 调试（闲置旧机即可）
- 能传数据的 USB 线（不要只能充电的线）

## 用法

| 操作 | 作用 |
| --- | --- |
| 点预览画面 | 对你点的那一块找焦（工作台 / 扫描都算） |
| 重新对焦 | 对画面中心再找一次，**不重启取流** |
| 变焦拉条 | 相机变焦，预览中即时生效 |
| 旋转 | 只转电脑上的画面（点击坐标会还原到相机原图） |
| 设置 | 相机分辨率 / 帧率，录像路径 / 编码 / 码率，OCR 质量 |
| 扫描 | 连拍多页，设好 LM Studio 后可识别 |

### 可选：LM Studio OCR

预览、变焦、对焦、抓拍、录像可以单独用，OCR 不是必须的。

1. 打开 LM Studio，加载一个带视觉能力的模型。
2. 打开本地服务（默认 `http://127.0.0.1:1234/v1`）。
3. 如果服务在另一台电脑上，让它监听局域网，并在软件「设置」里填那个地址。

## 原理

电脑通过 ADB 把打过补丁的 scrcpy 4.1 server 写到手机（不安装成手机应用），和变焦走同一条 Camera2 会话。换一台新手机，只需授权一次 USB 调试。

```
手机镜头  --USB/ADB-->  补丁 scrcpy-server  -->  本 Windows 软件
```

协议仍是官方 scrcpy 4.1。下载官方 Windows 压缩包之后，软件会再拷回 `tools/vendor/scrcpy-server`，点选对焦才会在。

## 已知限制

- 部分华为机会在损坏的文件同步推送，或预览中跑 `dumpsys media.camera` 时把 USB 打成 `offline`。掉线了就拔线等几秒再插，不要连点重新检测。
- Camera2 **LIMITED** 机型的连续对焦会比官方相机 App 弱一截。
- 这不是投屏，不是 IP Webcam，也不是云端安防摄像头。

## 致谢

取流基于 Genymobile 的 [scrcpy](https://github.com/Genymobile/scrcpy)（Apache-2.0）。本项目对 server 做了连续自动对焦和点选对焦的小补丁。

## 许可

[Apache License 2.0](LICENSE)
