"""NDEF URI encoding and conservative NTAG215 writes via a PN532 adapter.
Only NDEF data pages are written. Lock/config/password pages are never changed.
"""
from __future__ import annotations

import time
from urllib.parse import urlparse


def encode_uri_tlv(url: str) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("NFC 链接必须为完整 HTTP(S) 地址")
    prefix = "https://" if url.startswith("https://") else "http://"
    code = 0x04 if prefix == "https://" else 0x03
    payload = bytes([code]) + url.removeprefix(prefix).encode("utf-8")
    if len(payload) <= 255:
        record = bytes([0xD1, 1, len(payload), 0x55]) + payload
    else:
        record = bytes([0xC1, 1]) + len(payload).to_bytes(4, "big") + b"U" + payload
    length = bytes([len(record)]) if len(record) < 255 else b"\xff" + len(record).to_bytes(2, "big")
    tlv = b"\x03" + length + record + b"\xfe"
    if len(tlv) > 496:
        raise ValueError("链接超出 NTAG215 默认 NDEF 容量 496 字节，请缩短 PUBLIC_BASE_URL")
    return tlv


class NTAG215Writer:
    def __init__(self, reader, connection=None):
        self.reader = reader
        self.connection = connection

    def close(self):
        if self.connection is not None:
            self.connection.close()

    def read_page(self, page: int) -> bytes:
        data = self.reader.ntag2xx_read_block(page)
        if data is None or len(data) < 4:
            raise IOError(f"标签读取失败（页 {page}），请保持标签不动")
        return bytes(data[:4])

    def ensure_uid(self, uid: bytes):
        current = self.reader.read_passive_target(timeout=0.5)
        if current is None or bytes(current) != uid:
            raise IOError("标签已移开或更换，已停止写入")

    def write_url(self, url: str, reserve=None, timeout: float = 30) -> dict:
        tlv = encode_uri_tlv(url)
        deadline = time.monotonic() + timeout
        uid = None
        while time.monotonic() < deadline:
            uid = self.reader.read_passive_target(timeout=0.5)
            if uid:
                break
        if not uid:
            raise TimeoutError("未检测到标签，请放置 NTAG215 后重试")
        uid = bytes(uid)
        if len(uid) != 7:
            raise ValueError("此驱动仅接收 7 字节 UID 的 NTAG215 标签")
        cc = self.read_page(3)
        if cc[:3] != b"\xe1\x10\x3e" or cc[3] != 0:
            raise ValueError("标签不是预期的可读写 NTAG215 配置（CC E1 10 3E 00）")
        padded = tlv + b"\x00" * (-len(tlv) % 4)
        existing = b"".join(self.read_page(4 + i) for i in range(len(padded) // 4))
        blank = existing[:3] == b"\x03\x00\xfe" or not any(existing)
        if not blank and existing[:len(tlv)] != tlv:
            raise ValueError("标签已有其他内容，请使用空白 NTAG215")
        uid_text = ":".join(f"{byte:02X}" for byte in uid)
        if reserve:
            reserve(uid_text)
        if existing[:len(tlv)] != tlv:
            # Invalidate NDEF first, then write body, and commit the first page last.
            self.ensure_uid(uid)
            if not self.reader.ntag2xx_write_block(4, b"\x03\x00\xfe\x00"):
                raise IOError("无法初始化 NDEF 数据区，标签可能已锁定")
            for offset in range(4, len(padded), 4):
                self.ensure_uid(uid)
                if not self.reader.ntag2xx_write_block(4 + offset // 4, padded[offset:offset + 4]):
                    raise IOError("标签写入失败，请保持标签不动后重试")
            self.ensure_uid(uid)
            if not self.reader.ntag2xx_write_block(4, padded[:4]):
                raise IOError("NDEF 提交失败，请重试")
        self.ensure_uid(uid)
        readback = b"".join(self.read_page(4 + i) for i in range(len(padded) // 4))
        if readback[:len(tlv)] != tlv:
            raise IOError("NFC 回读内容不一致，不能确认写入成功")
        return {"nfc_uid": uid_text, "readback_url": url, "ndef_bytes": len(tlv), "method": "pn532", "status": "readback_verified"}


def connect_pcr532(port: str | None = None):
    """Connect a PCR532 USB reader using the PN532 HSU serial protocol."""
    import os
    import serial
    from serial.tools import list_ports
    from adafruit_pn532.uart import PN532_UART

    port = port or os.environ.get("NFC_SERIAL_PORT", "").strip()
    if not port:
        # Identify the USB bridge, then verify the NFC controller below.
        candidates = [item.device for item in list_ports.comports()
                      if (item.vid, item.pid) == (0x1A86, 0x7523)]
        if not candidates:
            raise RuntimeError("未找到 PCR532 USB 串口，请检查 USB 连接，或设置 NFC_SERIAL_PORT")
        if len(candidates) != 1:
            raise RuntimeError("检测到多个 CH340 串口，请用 NFC_SERIAL_PORT 指定 PCR532")
        port = candidates[0]
    connection = serial.Serial(port, baudrate=115200, timeout=0.1, write_timeout=1, exclusive=True)
    try:
        reader = PN532_UART(connection, debug=False)
        if reader.firmware_version[0] != 0x32:
            raise RuntimeError("读写器未返回 PN532 固件标识，请核对 PCR532 的型号和 USB 协议")
        reader.SAM_configuration()
        return NTAG215Writer(reader, connection)
    except BaseException:
        connection.close()
        raise
