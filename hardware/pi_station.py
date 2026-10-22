#!/usr/bin/env python3
"""Headless Pi station: hold GPIO -> WAV -> shared API -> reserve -> NTAG215.
No recording or transcript is printed or retained by this process.
"""
from __future__ import annotations

import io
import json
import os
import signal
import threading
import time
import uuid
import wave
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ntag215 import connect_pn532

BASE = os.environ.get("WISHSTONE_API_URL", "http://127.0.0.1:8080").rstrip("/")
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "")


def api(path, payload=None, body=None, content_type="application/json"):
    if payload is not None:
        body = json.dumps(payload).encode()
    headers = {"Content-Type": content_type, "X-Device-Token": DEVICE_TOKEN}
    try:
        with urlopen(Request(BASE + path, data=body, headers=headers), timeout=120) as response:
            return json.loads(response.read())
    except HTTPError as error:
        # Only relay our own API's controlled error message, never request bodies.
        try:
            message = json.loads(error.read()).get("error", "API 请求失败")
        except (ValueError, UnicodeDecodeError):
            message = "API 请求失败"
        raise RuntimeError(message) from None


def submit_audio(pcm: bytes):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000); output.writeframes(pcm)
    boundary = "wishstone-" + uuid.uuid4().hex
    fields = {}
    if os.environ.get("VENUE_ID"):
        fields["venue_id"] = os.environ["VENUE_ID"]
    if os.environ.get("DEVICE_ID"):
        fields["device_id"] = os.environ["DEVICE_ID"]
    body = b""
    for key, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    body += f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="wish.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + buffer.getvalue() + f'\r\n--{boundary}--\r\n'.encode()
    return api("/api/sessions", body=body, content_type="multipart/form-data; boundary=" + boundary)["session"]


def main():
    import sounddevice as sd
    from gpiozero import Button, LED

    if not DEVICE_TOKEN:
        raise SystemExit("请设置 DEVICE_TOKEN，并与主服务配置保持一致。")
    # Check that cross-device NFC links are configured before accepting wishes.
    if not api("/api/health")["public_url_configured"]:
        raise SystemExit("请先在主服务配置 PUBLIC_BASE_URL，确保纪念页可跨设备访问。")
    writer = connect_pn532()
    button = Button(int(os.environ.get("BUTTON_GPIO", "17")), pull_up=True, bounce_time=0.05)
    led = LED(int(os.environ["STATUS_LED_GPIO"])) if os.environ.get("STATUS_LED_GPIO") else None
    released = threading.Event()
    gate = threading.Lock()
    input_device = os.environ.get("AUDIO_INPUT_DEVICE")
    if input_device and input_device.isdigit():
        input_device = int(input_device)

    def work():
        session = None
        try:
            frames, errors = [], []
            def callback(data, frame_count, timing, status):
                if status:
                    errors.append(True)
                frames.append(bytes(data))
            if led:
                led.on()
            print("recording", flush=True)
            started = time.monotonic()
            with sd.RawInputStream(samplerate=16000, channels=1, dtype="int16", device=input_device, callback=callback):
                released.wait(timeout=60)
            if led:
                led.blink(on_time=0.2, off_time=0.2)
            if errors:
                raise RuntimeError("麦克风录音丢帧，请检查设备与采样率")
            pcm = b"".join(frames)[:16000 * 2 * 60]
            if len(pcm) < 16000 * 2 * 0.3:
                raise RuntimeError("录音太短，请重新按住说话")
            session = submit_audio(pcm)
            print("wish_created; place_blank_ntag215", flush=True)
            nfc = api(f"/api/sessions/{session['slug']}/nfc")["nfc"]
            binding = {"blessing_session_id": session["id"], "souvenir_sku": session["selected_souvenir"]["sku"]}
            def reserve(uid):
                api("/api/nfc/bind", {**binding, "nfc_uid": uid})
            # Retry writing the same wish; never create another session on tag errors.
            while True:
                try:
                    receipt = writer.write_url(nfc["url"], reserve=reserve)
                    break
                except (OSError, ValueError, TimeoutError, RuntimeError) as error:
                    print(f"NFC 待重试：{error}。按住按钮后松开，重试当前心愿的标签。", flush=True)
                    released.clear()
                    released.wait()
            while True:
                try:
                    api("/api/nfc/bind", {**binding, **receipt})
                    break
                except Exception as error:
                    print(f"芯片回读已通过，回执待重试：{type(error).__name__}。按下并松开按钮重试登记，无需重新写卡。", flush=True)
                    released.clear(); released.wait()
            print("device_reported_readback_verified", flush=True)
        except Exception as error:
            print(f"station_error: {type(error).__name__}: {error}", flush=True)
        finally:
            if led:
                led.off()
            gate.release()
            print("ready", flush=True)

    def press():
        if not gate.acquire(blocking=False):
            return
        released.clear()
        threading.Thread(target=work, daemon=True).start()

    button.when_pressed = press
    button.when_released = released.set
    print("ready", flush=True)
    try:
        signal.pause()
    finally:
        released.set(); button.close()
        if led:
            led.close()


if __name__ == "__main__":
    main()
