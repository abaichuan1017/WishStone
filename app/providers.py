"""Small vendor-neutral HTTP adapter. Audio is never replaced by invented text."""
from __future__ import annotations

import json
import os
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ProviderError(Exception):
    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.status = status


def transcribe(audio: bytes, mime_type: str, filename: str) -> dict:
    endpoint = os.environ.get("ASR_HTTP_URL", "").strip()
    if not endpoint:
        raise ProviderError("语音转写服务尚未配置。可以先写下心愿，或配置 ASR_HTTP_URL 后使用录音。")
    boundary = "wishstone-" + uuid.uuid4().hex
    # Use a generated filename rather than interpolating untrusted upload headers.
    safe_name = "recording." + {"audio/webm": "webm", "audio/mp4": "m4a", "audio/wav": "wav", "audio/ogg": "ogg"}.get(mime_type.split(";")[0], "bin")
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\nzh\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="{safe_name}"\r\n'
            f'Content-Type: {mime_type.split(";")[0]}\r\n\r\n').encode() + audio + f"\r\n--{boundary}--\r\n".encode()
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    token = os.environ.get("ASR_API_TOKEN", "")
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urlopen(Request(endpoint, data=body, headers=headers, method="POST"), timeout=float(os.environ.get("ASR_TIMEOUT_SECONDS", "120"))) as response:
            data = json.loads(response.read(1024 * 1024))
        text = data.get("text", "") if isinstance(data, dict) else ""
        if not isinstance(text, str) or not text.strip():
            raise ProviderError("没有识别到清晰的心愿，请重新录音或写下心愿。", 422)
        if len(text) > 1000:
            raise ProviderError("转写内容过长，请将心愿控制在 1000 字以内。", 422)
        return {"text": text.strip(), "provider": "sensevoice-sherpa-onnx" if data.get("provider") == "sensevoice-sherpa-onnx" else "http-asr", "confidence": None, "segments": []}
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError) as error:
        # Never surface upstream response bodies, URLs or tokens.
        raise ProviderError("语音转写服务暂时不可用，请稍后重试或写下心愿。", 502) from error
