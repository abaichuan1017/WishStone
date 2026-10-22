# 树莓派 4 部署

硬件：树莓派 4、USB 麦克风、按钮、PCR532 USB 读写器、NTAG215 NFC 贴纸。使用 64 位 Raspberry Pi OS 和 Python 3.10+。

NTAG215 是 NFC 芯片型号，可封装成贴纸、卡片或嵌入纪念品。这里使用贴纸，将纪念页链接写入后，手机轻触即可打开。

## 1. 安装

```bash
sudo apt update
sudo apt install python3-venv python3-dev ffmpeg libportaudio2 usbutils
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -r requirements-asr.txt -r requirements-pi.txt
```

## 2. 连接 PCR532

将读写器插入树莓派 USB 口，执行：

```bash
python -m serial.tools.list_ports -v
python hardware/check_reader.py
```

返回 PN532 固件版本表示连接成功。放上 NTAG215 贴纸，检查读卡：

```bash
python hardware/check_reader.py --tag
```

这两条检查不会写入贴纸。验证写入时使用一枚空白贴纸：

```bash
python hardware/check_reader.py --write-url https://example.com/
```

出现“写入与回读通过”后，用手机轻触贴纸检查链接。

程序自动选择唯一的 CH340 USB 串口。存在多个串口时，按第一条命令的结果指定：

```bash
NFC_SERIAL_PORT=/dev/ttyUSB0 python hardware/check_reader.py --tag
```

遇到权限错误，将运行用户加入 `dialout` 组，退出登录后重新进入：

```bash
sudo usermod -aG dialout "$USER"
```

本项目使用 **PN532 HSU 串口协议，115200 波特率**。树莓派内核提供 CH340 的 `ch341` 驱动，Python 使用 `pyserial` 与 `adafruit-circuitpython-pn532`。无需 I²C 接线或开启 GPIO 串口。若插入后没有串口，先检查数据线和 `lsusb`，再执行 `sudo modprobe ch341`。

已核对内核驱动和 Python 接口；当前未连接这台实物。是否兼容，以读取固件版本、贴纸写入回读和手机打开结果为准。

## 3. 按钮与麦克风

按钮两端分别连接 GPIO17 和 GND，使用内部上拉。代码使用 BCM 编号；GPIO17 是物理 11 脚，GND 可用物理 6 脚。

USB 麦克风插入树莓派，执行 `python -m sounddevice` 查看输入设备。需要指定设备时，在 `.env` 设置 `AUDIO_INPUT_DEVICE`。状态灯可通过 `STATUS_LED_GPIO` 配置。

## 4. SenseVoice

下载 INT8 模型，模型文件遵循模型仓库的许可：

```bash
pip install huggingface_hub
hf download csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17 \
  model.int8.onnx tokens.txt LICENSE --local-dir models/sensevoice
```

## 5. 配置与运行

复制 `.env.example` 为 `.env`，至少填写：

- `PUBLIC_BASE_URL`：手机能够访问的纪念页服务地址。
- `DEVICE_TOKEN`：主服务和硬件代理共用的自设随机值。
- `NFC_SERIAL_PORT`：留空自动识别，或指定 PCR532 串口。
- `VENUE_CONFIG`：当前场馆配置文件。

每个终端先加载配置并激活环境，再分别启动三个进程：

```bash
. .venv/bin/activate
set -a
. ./.env
set +a

python3 services/sensevoice_server.py
# 另一个终端：python3 app/server.py
# 再一个终端：python3 hardware/pi_station.py
```

流程：按住按钮录音 → 松开转写和分类 → 放上空白贴纸 → 写入链接并回读。写卡失败时，按下再松开按钮，重试当前心愿。

[systemd 文件](../deploy/) 可用于开机启动，安装前修改运行用户和 `/opt/wishstone` 路径，确保用户有串口、GPIO 和音频设备权限。模型耗时、录音质量与现场 NFC 感应效果需要实机检查。

接口与资料：

- [PCR532 USB 协议实现](https://github.com/touzi/PCR532)：CH340 USB 串口与 PN532 HSU。
- [树莓派 CH341 内核驱动](https://github.com/raspberrypi/linux/blob/rpi-6.12.y/drivers/usb/serial/ch341.c)：包含 USB ID `1a86:7523`。
- [Adafruit PN532 串口接口](https://docs.circuitpython.org/projects/pn532/en/latest/api.html#module-adafruit_pn532.uart)。
- [NXP NTAG213/215/216 数据手册](https://www.nxp.com/docs/en/data-sheet/NTAG213_215_216.pdf)：NTAG215 为 NFC Forum Type 2 芯片，用户区 504 字节；当前写入器遵循默认 CC 声明的 496 字节 NDEF 区域。
- [SenseVoice ONNX 运行方式](https://k2-fsa.github.io/sherpa/onnx/sense-voice/python-api.html)。
