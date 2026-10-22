#!/usr/bin/env python3
"""Optional local SenseVoice INT8 HTTP adapter, suitable for a separate Pi process.
Requires sherpa-onnx, numpy, ffmpeg and separately downloaded model files.
"""
from __future__ import annotations

import hmac
import os
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from server import APIError, json_response, parse_body


def main() -> None:
    import numpy as np
    import sherpa_onnx

    model_dir = Path(os.environ.get("SENSEVOICE_MODEL_DIR", "models/sensevoice"))
    model, tokens = model_dir / "model.int8.onnx", model_dir / "tokens.txt"
    if not model.is_file() or not tokens.is_file():
        raise SystemExit("缺少 SenseVoice 模型；请按 docs/raspberry-pi.md 下载 model.int8.onnx 和 tokens.txt。")
    if not shutil.which("ffmpeg"):
        raise SystemExit("缺少 ffmpeg；请先安装系统音频解码工具。")
    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(model), tokens=str(tokens), num_threads=int(os.environ.get("ASR_THREADS", "2")),
        language=os.environ.get("ASR_LANGUAGE", "zh"), use_itn=True, debug=False,
    )
    slot = threading.BoundedSemaphore(1)
    api_token = os.environ.get("ASR_API_TOKEN", "")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                return json_response(self, {"error": "not found"}, 404)
            return json_response(self, {"provider": "sensevoice-sherpa-onnx", "model_loaded": True})

        def do_POST(self):
            if self.path != "/transcribe":
                return json_response(self, {"error": "not found"}, 404)
            if api_token and not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + api_token):
                return json_response(self, {"error": "unauthorized"}, 401)
            if not slot.acquire(blocking=False):
                return json_response(self, {"error": "识别服务忙，请稍后重试"}, 429)
            try:
                audio = parse_body(self).get("audio")
                if not isinstance(audio, dict) or not audio.get("content"):
                    raise APIError("缺少录音")
                decoded = subprocess.run(
                    ["ffmpeg", "-v", "error", "-i", "pipe:0", "-t", "61", "-vn", "-f", "f32le", "-ar", "16000", "-ac", "1", "pipe:1"],
                    input=audio["content"], capture_output=True, timeout=20, check=True,
                ).stdout
                samples = np.frombuffer(decoded, dtype=np.float32)
                if len(samples) < 4800 or len(samples) > 16000 * 60:
                    raise APIError("录音时长应为 0.3–60 秒", 422)
                stream = recognizer.create_stream()
                stream.accept_waveform(16000, samples)
                recognizer.decode_stream(stream)
                text = re.sub(r"<\|[^|]*\|>", "", stream.result.text).strip()
                if not text:
                    raise APIError("没有识别到清晰语音", 422)
                return json_response(self, {"text": text, "provider": "sensevoice-sherpa-onnx"})
            except APIError as error:
                return json_response(self, {"error": str(error)}, error.status)
            except (subprocess.SubprocessError, ValueError):
                return json_response(self, {"error": "录音解码失败"}, 422)
            except Exception:
                return json_response(self, {"error": "识别失败，请检查模型与运行环境"}, 500)
            finally:
                slot.release()

    host, port = os.environ.get("ASR_HOST", "127.0.0.1"), int(os.environ.get("ASR_PORT", "8091"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"SenseVoice ready: http://{host}:{port}/transcribe", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
