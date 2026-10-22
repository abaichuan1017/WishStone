#!/usr/bin/env python3
"""Check a PCR532 USB connection; tag writes require an explicit --write-url."""
from __future__ import annotations

import argparse
import sys
import time

from ntag215 import connect_pcr532


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 PCR532 USB 读写器与 NTAG215 NFC 贴纸")
    parser.add_argument("--port", help="USB 串口路径，也可通过 NFC_SERIAL_PORT 设置")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--tag", action="store_true", help="读取贴纸配置，不写入")
    action.add_argument("--write-url", metavar="URL", help="将链接写入空白贴纸，并回读校验")
    args = parser.parse_args()
    writer = None
    try:
        writer = connect_pcr532(args.port)
        _, major, minor, _ = writer.reader.firmware_version
        print(f"PCR532 连接通过：{writer.connection.port}，PN532 固件 {major}.{minor}")
        if args.write_url:
            print("请放置空白 NTAG215 贴纸，等待写入并回读。", flush=True)
            receipt = writer.write_url(args.write_url)
            print(f"写入与回读通过：{receipt['ndef_bytes']} 字节 NDEF 数据")
        elif args.tag:
            print("请放置 NTAG215 贴纸，等待读取。", flush=True)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                uid = writer.reader.read_passive_target(timeout=0.5)
                if uid:
                    writer.ensure_uid(bytes(uid))
                    if len(uid) != 7 or writer.read_page(3) != b"\xe1\x10\x3e\x00":
                        raise ValueError("贴纸不符合当前 NTAG215 可读写配置")
                    print("NTAG215 读卡检查通过，未写入贴纸。")
                    break
            else:
                raise TimeoutError("未检测到贴纸，请靠近读写器后重试")
        return 0
    except Exception as error:
        print(f"检查失败：{error}", file=sys.stderr)
        return 1
    finally:
        if writer is not None:
            writer.close()


if __name__ == "__main__":
    raise SystemExit(main())
