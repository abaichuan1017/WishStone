# 树莓派 4 参考部署

目标为 64 位 Raspberry Pi OS、Python 3.10+、USB 麦克风、按钮、PN532 和 NTAG215。下面是参考接法与脚本，尚未在本次工作中接触实物。树莓派内存型号、麦克风采样率、模型耗时及 PN532 模块引脚需要现场核验。

## 1. 环境

```bash
sudo apt update
sudo apt install python3-venv python3-dev ffmpeg libportaudio2 i2c-tools
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -r requirements-asr.txt -r requirements-pi.txt
```

用 `sudo raspi-config` 开启 I²C。PN532 设置为 I²C 模式，安装后用 `i2cdetect -y 1` 检查模块地址。使用 `python -m sounddevice` 列出录音设备，把编号填入 `AUDIO_INPUT_DEVICE`。不需要安装 Pi 依赖来运行电脑上的文字演示。

## 2. 获取 SenseVoice 模型

采用 sherpa-onnx 提供的 SenseVoice INT8 模型；与原项目的 FunASR/PyTorch 加载方式是两条不同运行路径。模型许可见模型仓库，不将模型文件提交本仓库。

```bash
pip install huggingface_hub
hf download csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17 \
  model.int8.onnx tokens.txt LICENSE --local-dir models/sensevoice
```

此模型目录和文件名已通过 Hub 元数据核对；未在本次开发中下载权重或测量性能。`ASR_THREADS=2` 为参考起点，可结合温度、内存和实际音频耗时调整。

```bash
python3 services/sensevoice_server.py
# 另一个终端：
ASR_HTTP_URL=http://127.0.0.1:8091/transcribe python3 app/server.py
```

HTTP 服务默认分别监听 `127.0.0.1:8091` 和 `127.0.0.1:8080`。模型启动失败时不接受伪造转写。可把 ASR 部署在另一台局域网机器，修改 URL 即可；暴露网络接口时按实际网络环境配置访问控制。

## 3. 按钮与 PN532

代码使用 **BCM GPIO 编号**。本驱动按 Adafruit PN532 文档的树莓派 I²C 唤醒接法，提供 `REQ/P32` 和 `RESET`；若模块没有这些引脚，应按该模块文档修改 `connect_pn532()` 或换用 SPI/UART 驱动。

| 连接 | 树莓派引脚 |
| --- | --- |
| 按钮一端 | GPIO17，物理 11 脚 |
| 按钮另一端 | GND，物理 6 脚；内部上拉 |
| PN532 SDA | GPIO2 / SDA，物理 3 脚 |
| PN532 SCL | GPIO3 / SCL，物理 5 脚 |
| PN532 GND | GND |
| PN532 REQ / P32 | GPIO12，物理 32 脚；可改 `PN532_REQ_GPIO` |
| PN532 RESET | GPIO6，物理 31 脚；可改 `PN532_RESET_GPIO` |
| PN532 VCC | 按模块额定供电连接；Pi GPIO 逻辑电平为 3.3V |

`STATUS_LED_GPIO` 可选，使用外接带限流电阻的状态 LED；不设置则只打印阶段。模块与 NTAG215 均未在本次开发中实测。

## 4. 配置与启动

复制 `.env.example` 为 `.env`，填入自己的环境值。示例主程序不自动加载 dotenv；文件使用受控 `KEY=value` 格式，通过 systemd 或 shell 导入。

```bash
set -a
. ./.env
set +a
python3 app/server.py
```

在同样环境下另启 `python3 services/sensevoice_server.py` 与 `python3 hardware/pi_station.py`。至少配置：

- `DEVICE_TOKEN`：本机硬件代理与主服务使用相同的自设随机值，勿提交仓库。
- `PUBLIC_BASE_URL`：手机能访问的稳定地址；若为现场局域网地址，手机必须在相同网络且服务实际监听可达地址。需要长期带走访问时，应指向长期可用的纪念页服务。
- `ASR_HTTP_URL`：本地 SenseVoice 地址。
- `VENUE_CONFIG`：场景配置文件；多场馆时代理额外设置 `VENUE_ID/DEVICE_ID`。

物理流程为：按住按钮录音 → 松开提交 → 完成分类匹配 → LED 闪烁/终端提示放标签 → 空白 NTAG215 贴近 PN532 → 写入并回读 → 上报回执。NFC 出错后用同一按钮按下并松开重试当前心愿，不重新录音。该版本无自动出货控制。

[systemd 文件](../deploy/) 以 `/opt/wishstone` 和 `User=pi` 为模板，安装前按实际路径与用户修改。需确保运行用户拥有 GPIO、I²C 和音频设备访问权限。未在本机安装或启用这些服务。

## 5. 现场验收

使用一枚新标签完成一次真实语音流程，记录录音长度、转写文本、耗时、分类、SKU、标签 UID、回读地址及手机打开结果。确认超时、标签移开、标签已有内容和错误标签场景下不会误报成功。NTAG215 有 504 字节用户区，默认 CC 对 NDEF 声明 496 字节；驱动保守遵循后者，不触碰配置或锁位。

官方参考：

- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice)
- [sherpa-onnx 的 SenseVoice 支持与平台](https://k2-fsa.github.io/sherpa/onnx/sense-voice/index.html)
- [官方 Python 调用示例](https://k2-fsa.github.io/sherpa/onnx/sense-voice/python-api.html)
- [Adafruit PN532 API 与 Raspberry Pi I²C 接法](https://docs.circuitpython.org/projects/pn532/en/latest/api.html)
- [NXP NTAG213/215/216 数据手册，CC 和内存布局](https://www.nxp.com/docs/en/data-sheet/NTAG213_215_216.pdf)
- [Chrome Web NFC](https://developer.chrome.com/docs/capabilities/nfc)；浏览器适配路径需要兼容设备与安全上下文，不用于替代树莓派驱动。
