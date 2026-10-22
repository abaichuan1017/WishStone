#!/usr/bin/env python3
"""WishStone 2.0 local kiosk, API, durable sessions and NFC handoff."""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import secrets
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from domain import CATALOG, DEFAULT_VENUE_ID, VENUES, classify, make_design_brief, match_souvenirs, normalize_uid, reply_for
from providers import ProviderError, transcribe

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
DATA_DIR = Path(os.environ.get("WISHSTONE_DATA_DIR", str(ROOT)))
STORAGE_DIR = DATA_DIR / "storage"
USER_AUDIO_DIR = STORAGE_DIR / "user_audio"
DB_PATH = DATA_DIR / "wishstone.db"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
DEVICE_TOKEN = os.environ.get("DEVICE_TOKEN", "")
MAX_BODY = 12 * 1024 * 1024
AUDIO_TYPES = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mp4": ".m4a", "video/mp4": ".m4a"}


class APIError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    USER_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    with closing(get_conn()) as conn:
        legacy = conn.execute("SELECT name FROM sqlite_master WHERE name='blessing_session'").fetchone()
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(blessing_session)")}
        if legacy and "metadata_json" not in columns:
            backup_dir = DATA_DIR / "backups"
            backup_dir.mkdir(exist_ok=True)
            backup = backup_dir / f"wishstone-v1-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.db"
            with closing(sqlite3.connect(backup)) as target:
                conn.backup(target)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS venue (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, city TEXT,
                theme_style TEXT, prompt_template_id TEXT, tts_voice_id TEXT, is_active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS device (
                id TEXT PRIMARY KEY, venue_id TEXT NOT NULL REFERENCES venue(id), device_code TEXT NOT NULL,
                location_desc TEXT, status TEXT NOT NULL, last_online_at TEXT);
            CREATE TABLE IF NOT EXISTS prompt_template (
                id TEXT PRIMARY KEY, venue_id TEXT NOT NULL REFERENCES venue(id), role_name TEXT NOT NULL,
                system_prompt TEXT NOT NULL, response_style TEXT NOT NULL, forbidden_rules TEXT NOT NULL, version TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS blessing_session (
                id TEXT PRIMARY KEY, venue_id TEXT NOT NULL REFERENCES venue(id), device_id TEXT REFERENCES device(id),
                user_audio_url TEXT, asr_text TEXT NOT NULL, intent TEXT NOT NULL, sub_intent TEXT NOT NULL,
                emotion TEXT NOT NULL, safety TEXT NOT NULL, ai_reply_text TEXT NOT NULL, ai_reply_audio_url TEXT,
                blessing_page_slug TEXT NOT NULL UNIQUE, qr_code_url TEXT, created_at TEXT NOT NULL, review_status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS souvenir_nfc_binding (
                id TEXT PRIMARY KEY, blessing_session_id TEXT NOT NULL REFERENCES blessing_session(id),
                nfc_uid TEXT NOT NULL, souvenir_sku TEXT, bind_status TEXT NOT NULL, bind_time TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS nfc_tag_claim (
                nfc_uid TEXT PRIMARY KEY, blessing_session_id TEXT NOT NULL REFERENCES blessing_session(id));
            CREATE TABLE IF NOT EXISTS design_job (
                id TEXT PRIMARY KEY, blessing_session_id TEXT NOT NULL REFERENCES blessing_session(id),
                souvenir_sku TEXT NOT NULL, brief_json TEXT NOT NULL, created_at TEXT NOT NULL,
                UNIQUE(blessing_session_id, souvenir_sku));
        """)
        if "metadata_json" not in columns:
            conn.execute("ALTER TABLE blessing_session ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
        if "souvenir_sku" not in columns:
            conn.execute("ALTER TABLE blessing_session ADD COLUMN souvenir_sku TEXT")
        for venue in VENUES.values():
            prompt_id = "prompt-" + venue["id"]
            conn.execute("INSERT OR IGNORE INTO venue VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
                         (venue["id"], venue["name"], venue["type"], venue["city"], venue["theme"], prompt_id, ""))
            conn.execute("INSERT OR IGNORE INTO prompt_template VALUES (?, ?, ?, ?, ?, ?, 'v1')",
                         (prompt_id, venue["id"], venue["role_name"], "温和回应心愿，不作命运断言。", "简洁、温暖", "不作疗效或财富承诺"))
            conn.execute("INSERT OR IGNORE INTO device VALUES (?, ?, ?, ?, ?, ?)",
                         (venue["device_id"], venue["id"], venue["device_id"], "本地演示装置", "demo", now_iso()))
        # Preserve historical bindings and reserve their UIDs without rewriting them.
        for row in conn.execute("SELECT nfc_uid, blessing_session_id FROM souvenir_nfc_binding ORDER BY bind_time"):
            try:
                uid = normalize_uid(row["nfc_uid"])
            except ValueError:
                continue
            conn.execute("INSERT OR IGNORE INTO nfc_tag_claim VALUES (?, ?)", (uid, row["blessing_session_id"]))
        conn.commit()


def json_response(handler: SimpleHTTPRequestHandler, data: dict, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def parse_body(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise APIError("无效的请求长度")
    if length < 0 or length > MAX_BODY:
        raise APIError("请求过大，录音请控制在 60 秒和 12 MB 以内", 413)
    raw = handler.rfile.read(length)
    ctype = handler.headers.get_content_type()
    if ctype == "application/json":
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise APIError("JSON 格式不正确")
        if not isinstance(result, dict):
            raise APIError("请求内容必须是 JSON 对象")
        return result
    if ctype == "multipart/form-data":
        header = handler.headers.get("Content-Type", "")
        message = BytesParser(policy=policy.default).parsebytes(("Content-Type: " + header + "\r\nMIME-Version: 1.0\r\n\r\n").encode() + raw)
        if not message.is_multipart():
            raise APIError("录音上传格式不正确")
        result = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            content = part.get_payload(decode=True) or b""
            if part.get_filename() is not None:
                result[name] = {"filename": part.get_filename(), "content": content, "mime_type": part.get_content_type()}
            else:
                result[name] = content.decode("utf-8", errors="replace")
        return result
    raise APIError("请使用 JSON 或表单上传", 415)


def text_field(payload: dict, name: str, default: str = "") -> str:
    value = payload.get(name, default)
    if not isinstance(value, str):
        raise APIError(f"{name} 必须为文本")
    return value.strip()


def get_session(conn: sqlite3.Connection, slug: str) -> sqlite3.Row:
    row = conn.execute("SELECT s.*, v.name AS venue_name FROM blessing_session s JOIN venue v ON v.id=s.venue_id WHERE blessing_page_slug=?", (slug,)).fetchone()
    if not row:
        raise APIError("这份心愿不存在", 404)
    if row["review_status"] != "approved" or row["safety"] != "pass":
        raise APIError("这份心愿暂不可公开查看或写入", 403)
    return row


def public_session(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    metadata = json.loads(row["metadata_json"] or "{}")
    intent = metadata.get("intent") or classify(row["asr_text"], row["venue_id"])
    souvenirs = match_souvenirs(row["venue_id"], intent) if row["venue_id"] in VENUES else []
    selected = next((item for item in souvenirs if item["sku"] == row["souvenir_sku"]), None)
    return {
        "id": row["id"], "slug": row["blessing_page_slug"], "venue_id": row["venue_id"], "venue_name": metadata.get("venue", {}).get("name", row["venue_name"]),
        "device_id": row["device_id"], "role_name": metadata.get("venue", {}).get("role_name", VENUES.get(row["venue_id"], {}).get("role_name", "守护者")),
        "asr": metadata.get("asr", {"text": row["asr_text"], "provider": "legacy", "confidence": None}),
        "asr_text": row["asr_text"], "intent": intent, "emotion": row["emotion"], "safety": row["safety"],
        "ai_reply_text": row["ai_reply_text"], "ai_reply_audio_url": None, "tts": {"status": "not-configured"},
        "user_audio_url": row["user_audio_url"], "created_at": row["created_at"],
        "blessing_page_url": "/b/" + row["blessing_page_slug"], "souvenirs": souvenirs, "selected_souvenir": selected,
        "nfc_bindings": [dict(item) for item in conn.execute("SELECT id, nfc_uid, souvenir_sku, bind_status, bind_time FROM souvenir_nfc_binding WHERE blessing_session_id=?", (row["id"],))],
    }


def nfc_payload(row: sqlite3.Row) -> dict:
    base = os.environ.get("PUBLIC_BASE_URL", "").strip().rstrip("/")
    parsed = urlparse(base)
    configured = bool(parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.query and not parsed.fragment and not parsed.username)
    if base and not configured:
        raise APIError("PUBLIC_BASE_URL 配置无效，请设置可跨设备访问的完整地址", 503)
    url = (base if configured else "http://localhost:" + os.environ.get("PORT", "8080")) + "/b/" + row["blessing_page_slug"]
    return {"status": "prepared", "url": url, "records": [{"recordType": "url", "data": url}],
            "public_url_configured": configured, "estimated_ndef_bytes": len(url.encode()) + 8,
            "notice": "写入后需重新读取标签验证；默认 localhost 链接仅可在此电脑访问。"}


class WishStoneHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def require_admin(self) -> None:
        token = self.headers.get("X-Admin-Token", "")
        if not ADMIN_TOKEN or not hmac.compare_digest(token, ADMIN_TOKEN):
            raise APIError("管理接口未授权；请设置 ADMIN_TOKEN 并提交对应请求头", 401)

    def do_GET(self) -> None:
        try:
            self.route_get()
        except APIError as error:
            json_response(self, {"error": str(error)}, error.status)

    def route_get(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/health":
            return json_response(self, {"version": "2.0.0", "asr": "configured" if os.environ.get("ASR_HTTP_URL") else "not-configured", "nlp": "local-rules", "tts": "not-configured", "model_3d": "brief-only", "nfc": "web-nfc-or-external-writer", "public_url_configured": bool(os.environ.get("PUBLIC_BASE_URL"))})
        if path == "/api/venues":
            with closing(get_conn()) as conn:
                active = {r["id"] for r in conn.execute("SELECT id FROM venue WHERE is_active=1")}
            return json_response(self, {"venues": [v for v in VENUES.values() if v["id"] in active], "notice": CATALOG["notice"]})
        if path.startswith("/api/venues/") and path.endswith("/souvenirs"):
            venue = VENUES.get(path.split("/")[3])
            if not venue:
                raise APIError("场馆不存在", 404)
            return json_response(self, {"souvenirs": venue["souvenirs"], "notice": CATALOG["notice"]})
        if path.startswith("/api/sessions/"):
            parts = path.strip("/").split("/")
            if len(parts) not in {3, 4} or (len(parts) == 4 and parts[3] != "nfc"):
                raise APIError("接口不存在", 404)
            with closing(get_conn()) as conn:
                row = get_session(conn, parts[2])
                return json_response(self, {"nfc": nfc_payload(row)} if len(parts) == 4 else {"session": public_session(conn, row)})
        if path.startswith("/api/admin/"):
            self.require_admin()
            return self.admin_get(path, parse_qs(parsed.query))
        if path.startswith("/media/"):
            media_path = (STORAGE_DIR / path.removeprefix("/media/")).resolve()
            if not media_path.is_relative_to(STORAGE_DIR.resolve()) or not media_path.is_file():
                raise APIError("文件不存在", 404)
            # Old audio assets remain on disk; only approved session media can be served.
            with closing(get_conn()) as conn:
                allowed = conn.execute("SELECT id FROM blessing_session WHERE (user_audio_url=? OR ai_reply_audio_url=?) AND review_status='approved' AND safety='pass'", (path, path)).fetchone()
            if not allowed:
                raise APIError("这份录音暂不可访问", 403)
            body = media_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(str(media_path))[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/api/"):
            raise APIError("接口不存在", 404)
        self.path = "/blessing.html" if path.startswith("/b/") else "/admin.html" if path == "/admin" else "/index.html" if path == "/" else self.path
        return super().do_GET()

    def do_POST(self) -> None:
        try:
            # Same-origin mutations; no wildcard CORS for kiosk or admin data.
            origin = self.headers.get("Origin")
            if origin and urlparse(origin).netloc != self.headers.get("Host"):
                raise APIError("不允许跨站提交", 403)
            self.route_post()
        except (APIError, ProviderError) as error:
            json_response(self, {"error": str(error)}, error.status)
        except sqlite3.IntegrityError:
            json_response(self, {"error": "记录冲突，请刷新后重试"}, 409)

    def route_post(self) -> None:
        path = urlparse(self.path).path
        if path.startswith("/api/admin/"):
            self.require_admin()
            return self.admin_post(path, parse_body(self))
        payload = parse_body(self)
        if path == "/api/transcriptions":
            audio = self.validate_audio(payload)
            return json_response(self, {"asr": transcribe(audio["content"], audio["mime_type"], audio["filename"])})
        if path == "/api/sessions":
            return self.create_session(payload)
        if path == "/api/nfc/bind":
            return self.bind_nfc(payload)
        if path.startswith("/api/sessions/") and path.endswith("/souvenir"):
            return self.select_souvenir(path.split("/")[3], payload)
        if path == "/api/design-jobs":
            return self.create_design_job(payload)
        raise APIError("接口不存在", 404)

    def validate_audio(self, payload: dict) -> dict:
        audio = payload.get("audio")
        if not isinstance(audio, dict) or not audio.get("content"):
            raise APIError("请上传有效录音")
        if audio["mime_type"] not in AUDIO_TYPES:
            raise APIError("暂不支持此录音格式", 415)
        return audio

    def create_session(self, payload: dict) -> None:
        venue_id = text_field(payload, "venue_id", DEFAULT_VENUE_ID)
        if venue_id not in VENUES:
            raise APIError("场馆不存在", 404)
        device_id = text_field(payload, "device_id", VENUES[venue_id]["device_id"])
        text = text_field(payload, "user_text")
        if len(text) > 1000:
            raise APIError("心愿请控制在 1000 字以内")
        audio = self.validate_audio(payload) if payload.get("audio") else None
        if not text and not audio:
            raise APIError("请按住录音，或先写下你的心愿")
        with closing(get_conn()) as conn:
            venue = conn.execute("SELECT id FROM venue WHERE id=? AND is_active=1", (venue_id,)).fetchone()
            device = conn.execute("SELECT id FROM device WHERE id=? AND venue_id=?", (device_id, venue_id)).fetchone()
            if not venue or not device:
                raise APIError("场馆与装置不匹配或不可用")
            asr = {"text": text, "provider": "user-text", "confidence": None, "segments": []} if text else transcribe(audio["content"], audio["mime_type"], audio["filename"])
            intent = classify(asr["text"], venue_id)
            if intent["safety"] != "pass":
                raise APIError("这份内容暂不适合生成纪念品。请照顾好自己，也可以换一种方式表达心愿。", 422)
            souvenirs = match_souvenirs(venue_id, intent)
            session_id = "sess-" + uuid.uuid4().hex
            slug = secrets.token_urlsafe(18)
            audio_url = ""
            audio_path = None
            # Audio storage is explicitly opt-in in 2.0; ASR upload is transient.
            if audio and text_field(payload, "retain_audio") == "true":
                audio_path = USER_AUDIO_DIR / (uuid.uuid4().hex + AUDIO_TYPES[audio["mime_type"]])
                audio_path.write_bytes(audio["content"])
                audio_url = "/media/user_audio/" + audio_path.name
            metadata = json.dumps({"asr": asr, "intent": intent, "venue": {"name": VENUES[venue_id]["name"], "role_name": VENUES[venue_id]["role_name"]}}, ensure_ascii=False)
            try:
                conn.execute("""INSERT INTO blessing_session
                    (id, venue_id, device_id, user_audio_url, asr_text, intent, sub_intent, emotion, safety,
                     ai_reply_text, ai_reply_audio_url, blessing_page_slug, qr_code_url, created_at, review_status, metadata_json, souvenir_sku)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, 'approved', ?, ?)""",
                    (session_id, venue_id, device_id, audio_url, asr["text"], intent["intent"], intent["sub_intent"], intent["emotion"], intent["safety"], reply_for(venue_id, intent), slug, "/b/" + slug, now_iso(), metadata, souvenirs[0]["sku"]))
                conn.commit()
            except Exception:
                if audio_path:
                    audio_path.unlink(missing_ok=True)
                raise
            row = get_session(conn, slug)
            return json_response(self, {"session": public_session(conn, row)}, 201)

    def select_souvenir(self, slug: str, payload: dict) -> None:
        sku = text_field(payload, "souvenir_sku")
        with closing(get_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = get_session(conn, slug)
            venue = VENUES.get(row["venue_id"])
            if not venue:
                raise APIError("此历史场景未加载，暂不可更换款式", 409)
            if sku not in {item["sku"] for item in venue["souvenirs"]}:
                raise APIError("请选择当前场馆的纪念品")
            if conn.execute("SELECT id FROM souvenir_nfc_binding WHERE blessing_session_id=?", (row["id"],)).fetchone():
                raise APIError("此心愿已绑定纪念品，暂不能更换款式", 409)
            conn.execute("UPDATE blessing_session SET souvenir_sku=? WHERE id=?", (sku, row["id"]))
            conn.commit()
            return json_response(self, {"session": public_session(conn, get_session(conn, slug))})

    def bind_nfc(self, payload: dict) -> None:
        session_id = text_field(payload, "blessing_session_id")
        try:
            uid = normalize_uid(text_field(payload, "nfc_uid"))
        except ValueError as error:
            raise APIError(str(error))
        method = text_field(payload, "method", "manual")
        if method not in {"manual", "web-nfc", "pn532"}:
            raise APIError("不支持的写入方式")
        if method == "pn532":
            token = self.headers.get("X-Device-Token", "")
            if not DEVICE_TOKEN or not hmac.compare_digest(token, DEVICE_TOKEN):
                raise APIError("装置未授权，请检查 DEVICE_TOKEN", 401)
        with closing(get_conn()) as conn:
            conn.execute("BEGIN IMMEDIATE")
            raw = conn.execute("SELECT blessing_page_slug FROM blessing_session WHERE id=?", (session_id,)).fetchone()
            if not raw:
                raise APIError("心愿不存在", 404)
            row = get_session(conn, raw["blessing_page_slug"])
            sku = text_field(payload, "souvenir_sku", row["souvenir_sku"] or "")
            if not sku or sku != row["souvenir_sku"]:
                raise APIError("纪念品与当前选择不匹配")
            status = "registered"
            if method in {"web-nfc", "pn532"}:
                expected = nfc_payload(row)
                if not expected["public_url_configured"]:
                    raise APIError("请先配置 PUBLIC_BASE_URL，再写入可跨设备打开的 NFC 链接")
                if text_field(payload, "readback_url") != expected["url"]:
                    raise APIError("标签回读地址不一致，请重新校验")
                status = "device_verified" if method == "pn532" else "client_verified"
            claim = conn.execute("SELECT blessing_session_id FROM nfc_tag_claim WHERE nfc_uid=?", (uid,)).fetchone()
            if claim and claim["blessing_session_id"] != session_id:
                raise APIError("这枚标签已绑定其他心愿，请换一枚标签", 409)
            existing = conn.execute("SELECT * FROM souvenir_nfc_binding WHERE blessing_session_id=? AND nfc_uid=?", (session_id, uid)).fetchone()
            if existing:
                if status in {"client_verified", "device_verified"} and existing["bind_status"] == "registered":
                    conn.execute("UPDATE souvenir_nfc_binding SET bind_status=? WHERE id=?", (status, existing["id"]))
                else:
                    status = existing["bind_status"]
                bind_id = existing["id"]
            else:
                bind_id = "bind-" + uuid.uuid4().hex
                conn.execute("INSERT OR IGNORE INTO nfc_tag_claim VALUES (?, ?)", (uid, session_id))
                conn.execute("INSERT INTO souvenir_nfc_binding VALUES (?, ?, ?, ?, ?, ?)", (bind_id, session_id, uid, sku, status, now_iso()))
            conn.commit()
            return json_response(self, {"binding": {"id": bind_id, "status": status, "nfc_uid": uid, "verification": "装置报告已写入并回读校验" if status == "device_verified" else "浏览器报告已回读校验" if status == "client_verified" else "仅数据库登记，不代表芯片已写入"}})

    def create_design_job(self, payload: dict) -> None:
        slug = text_field(payload, "slug")
        with closing(get_conn()) as conn:
            row = get_session(conn, slug)
            venue = VENUES.get(row["venue_id"], {})
            souvenir = next((item for item in venue.get("souvenirs", []) if item["sku"] == row["souvenir_sku"]), None)
            if not souvenir or not souvenir.get("customizable"):
                raise APIError("这件纪念品暂不提供定制设计任务", 409)
            brief = make_design_brief(row["venue_id"], souvenir, row["intent"])
            conn.execute("INSERT OR IGNORE INTO design_job VALUES (?, ?, ?, ?, ?)", ("design-" + uuid.uuid4().hex, row["id"], souvenir["sku"], json.dumps(brief, ensure_ascii=False), now_iso()))
            conn.commit()
            job = conn.execute("SELECT * FROM design_job WHERE blessing_session_id=? AND souvenir_sku=?", (row["id"], souvenir["sku"])).fetchone()
            return json_response(self, {"job": {"id": job["id"], **json.loads(job["brief_json"])}}, 201)

    def admin_get(self, path: str, query: dict) -> None:
        with closing(get_conn()) as conn:
            if path == "/api/admin/stats":
                stats = dict(conn.execute("SELECT COUNT(*) AS total_sessions, SUM(safety='pass') AS safe_sessions, SUM(safety!='pass') AS blocked_sessions, SUM(review_status='approved') AS approved_sessions FROM blessing_session").fetchone())
                stats = {key: value or 0 for key, value in stats.items()}
                stats["top_intents"] = [dict(row) for row in conn.execute("SELECT intent, COUNT(*) AS count FROM blessing_session GROUP BY intent ORDER BY count DESC LIMIT 8")]
                return json_response(self, {"stats": stats})
            if path == "/api/admin/sessions":
                try:
                    limit = max(1, min(200, int(query.get("limit", ["30"])[0])))
                except ValueError:
                    raise APIError("limit 应为数字")
                rows = conn.execute("SELECT s.*, v.name AS venue_name FROM blessing_session s JOIN venue v ON v.id=s.venue_id ORDER BY created_at DESC LIMIT ?", (limit,))
                return json_response(self, {"sessions": [dict(row) for row in rows]})
            if path == "/api/admin/nfc-bindings":
                rows = conn.execute("SELECT n.*, s.blessing_page_slug FROM souvenir_nfc_binding n JOIN blessing_session s ON s.id=n.blessing_session_id ORDER BY bind_time DESC LIMIT 100")
                return json_response(self, {"bindings": [dict(row) for row in rows]})
            if path.startswith("/api/admin/prompts/"):
                row = conn.execute("SELECT p.* FROM prompt_template p JOIN venue v ON v.prompt_template_id=p.id WHERE v.id=?", (path.split("/")[-1],)).fetchone()
                if not row:
                    raise APIError("配置不存在", 404)
                return json_response(self, {"prompt": dict(row)})
        raise APIError("接口不存在", 404)

    def admin_post(self, path: str, payload: dict) -> None:
        with closing(get_conn()) as conn:
            if path.startswith("/api/admin/sessions/") and path.endswith("/review"):
                status = text_field(payload, "review_status")
                if status not in {"pending", "approved", "blocked"}:
                    raise APIError("不支持的审核状态")
                result = conn.execute("UPDATE blessing_session SET review_status=? WHERE id=?", (status, path.split("/")[4]))
                if not result.rowcount:
                    raise APIError("心愿不存在", 404)
                conn.commit()
                return json_response(self, {"ok": True, "review_status": status})
            if path.startswith("/api/admin/prompts/"):
                fields = [text_field(payload, key) for key in ["role_name", "system_prompt", "response_style", "forbidden_rules"]]
                if not all(fields):
                    raise APIError("请填写完整配置")
                row = conn.execute("SELECT p.id, p.version FROM prompt_template p JOIN venue v ON v.prompt_template_id=p.id WHERE v.id=?", (path.split("/")[-1],)).fetchone()
                if not row:
                    raise APIError("配置不存在", 404)
                version = "v" + str(int(row["version"].removeprefix("v")) + 1) if row["version"].removeprefix("v").isdigit() else row["version"] + "-next"
                conn.execute("UPDATE prompt_template SET role_name=?, system_prompt=?, response_style=?, forbidden_rules=?, version=? WHERE id=?", (*fields, version, row["id"]))
                conn.commit()
                return json_response(self, {"ok": True, "version": version, "notice": "2.0 当前使用本地祝福模板；LLM 接入前，Prompt 配置仅保存备用。"})
        raise APIError("接口不存在", 404)


def run() -> None:
    init_db()
    port = int(os.environ.get("PORT", "8080"))
    host = os.environ.get("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), WishStoneHandler)
    print(f"WishStone 2.0: http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
