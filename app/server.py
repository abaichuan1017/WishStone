#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import os
import sqlite3
import uuid
import wave
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
STORAGE_DIR = ROOT / "storage"
USER_AUDIO_DIR = STORAGE_DIR / "user_audio"
AI_AUDIO_DIR = STORAGE_DIR / "ai_audio"
DB_PATH = ROOT / "wishstone.db"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "wishstone-admin")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS venue (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            city TEXT,
            theme_style TEXT,
            prompt_template_id TEXT,
            tts_voice_id TEXT,
            is_active INTEGER NOT NULL DEFAULT 1
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS device (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            device_code TEXT NOT NULL,
            location_desc TEXT,
            status TEXT NOT NULL,
            last_online_at TEXT,
            FOREIGN KEY (venue_id) REFERENCES venue(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prompt_template (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            role_name TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            response_style TEXT NOT NULL,
            forbidden_rules TEXT NOT NULL,
            version TEXT NOT NULL,
            FOREIGN KEY (venue_id) REFERENCES venue(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS blessing_session (
            id TEXT PRIMARY KEY,
            venue_id TEXT NOT NULL,
            device_id TEXT,
            user_audio_url TEXT,
            asr_text TEXT NOT NULL,
            intent TEXT NOT NULL,
            sub_intent TEXT NOT NULL,
            emotion TEXT NOT NULL,
            safety TEXT NOT NULL,
            ai_reply_text TEXT NOT NULL,
            ai_reply_audio_url TEXT,
            blessing_page_slug TEXT NOT NULL UNIQUE,
            qr_code_url TEXT,
            created_at TEXT NOT NULL,
            review_status TEXT NOT NULL,
            FOREIGN KEY (venue_id) REFERENCES venue(id),
            FOREIGN KEY (device_id) REFERENCES device(id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS souvenir_nfc_binding (
            id TEXT PRIMARY KEY,
            blessing_session_id TEXT NOT NULL,
            nfc_uid TEXT NOT NULL,
            souvenir_sku TEXT,
            bind_status TEXT NOT NULL,
            bind_time TEXT NOT NULL,
            FOREIGN KEY (blessing_session_id) REFERENCES blessing_session(id)
        )
        """
    )

    cur.execute("SELECT COUNT(*) AS c FROM venue")
    if cur.fetchone()["c"] == 0:
        venue_id = "venue-liangzhu"
        prompt_id = "prompt-liangzhu-v1"
        cur.execute(
            """
            INSERT INTO venue(id, name, type, city, theme_style, prompt_template_id, tts_voice_id, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                venue_id,
                "良渚文化博物馆",
                "museum",
                "杭州",
                "温润克制新中式",
                prompt_id,
                "voice-liangzhu-guardian",
            ),
        )

        cur.execute(
            """
            INSERT INTO prompt_template(id, venue_id, role_name, system_prompt, response_style, forbidden_rules, version)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                prompt_id,
                venue_id,
                "良渚文明守护者",
                "以温和、庄重、有文明传承感的方式回应来访者心愿，不作命运断言。",
                "60-120字，鼓励与安定并重，使用文明意象。",
                "禁止迷信承诺、医疗法律投资建议、极端判断。",
                "v1",
            ),
        )

        cur.execute(
            """
            INSERT INTO device(id, venue_id, device_code, location_desc, status, last_online_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "device-demo-001",
                venue_id,
                "LZ-ENTRANCE-01",
                "一层入口祈福体验区",
                "online",
                now_iso(),
            ),
        )

    conn.commit()
    conn.close()


def detect_safety(text: str) -> str:
    high_risk_keywords = [
        "自杀",
        "轻生",
        "炸弹",
        "暴力",
        "仇恨",
        "毒品",
        "博彩",
        "色情",
    ]
    lowered = text.lower()
    if any(k in text for k in high_risk_keywords) or "terror" in lowered:
        return "blocked"
    return "pass"


def detect_emotion(text: str) -> str:
    if any(k in text for k in ["焦虑", "紧张", "担心", "害怕"]):
        return "紧张与期待"
    if any(k in text for k in ["迷茫", "不知道", "困惑"]):
        return "迷茫与求索"
    if any(k in text for k in ["感谢", "感恩"]):
        return "感恩与平和"
    return "虔诚与期待"


def detect_intent(text: str) -> dict[str, str]:
    rules = [
        ("学业", "考研", ["考研", "上岸", "考试", "学业", "读书", "升学"]),
        ("事业", "求职", ["工作", "升职", "事业", "面试", "创业", "项目"]),
        ("爱情", "姻缘", ["姻缘", "爱情", "对象", "脱单", "感情", "婚姻"]),
        ("健康", "平安", ["健康", "平安", "身体", "康复", "家人"]),
        ("财运", "机缘", ["财运", "收入", "财富", "机缘", "生意"]),
    ]
    for intent, sub_intent, words in rules:
        if any(w in text for w in words):
            return {"intent": intent, "sub_intent": sub_intent}
    return {"intent": "人生", "sub_intent": "方向"}


def mock_asr_text(raw_text: str | None) -> tuple[str, float]:
    if raw_text and raw_text.strip():
        return raw_text.strip(), 0.96
    return "愿所念皆有回响，愿当下心安，步履坚定。", 0.62


def safe_reply(text: str) -> str:
    return "愿你平安顺遂，心绪安定。此刻请先照顾好自己，必要时及时向家人、朋友或专业机构求助。"


def generate_reply(venue_name: str, role_name: str, asr_text: str, intent: str, emotion: str, safety: str) -> str:
    if safety != "pass":
        return safe_reply(asr_text)

    if intent == "学业":
        core = "愿你所学如玉初琢，日日有进，终见光华。"
    elif intent == "事业":
        core = "愿你行路稳健，所付出的心力，都在时光里沉淀为收获。"
    elif intent == "爱情":
        core = "愿你心中有光，遇见真诚与理解，让缘分在从容中靠近。"
    elif intent == "健康":
        core = "愿你与家人身心安宁，晨昏皆稳，岁岁平和。"
    elif intent == "财运":
        core = "愿你把握机缘，守住本心，以踏实换来长久丰盈。"
    else:
        core = "愿你在前行中渐明方向，把每一步都走成心安与笃定。"

    return (
        f"这里是{venue_name}的{role_name}。"
        f"我听见了你的心愿，也感受到你的{emotion}。"
        f"{core}"
        "愿这份心意，被岁月温柔照见。"
    )


def synthesize_placeholder_audio(session_id: str, text: str) -> str:
    sample_rate = 22050
    duration = max(2.0, min(6.0, len(text) / 18))
    num_samples = int(sample_rate * duration)
    path = AI_AUDIO_DIR / f"{session_id}.wav"

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)

        frames = bytearray()
        for i in range(num_samples):
            t = i / sample_rate
            amplitude = 0.25 * math.sin(2 * math.pi * 440 * t)
            sample = int(amplitude * 32767)
            frames.extend(sample.to_bytes(2, byteorder="little", signed=True))
        wf.writeframes(bytes(frames))

    return f"/media/ai_audio/{path.name}"


def parse_json_body(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    content_length = int(handler.headers.get("Content-Length", "0") or 0)
    raw = handler.rfile.read(content_length) if content_length else b"{}"
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def parse_multipart_body(handler: SimpleHTTPRequestHandler) -> dict[str, Any]:
    content_type = handler.headers.get("Content-Type", "")
    if "boundary=" not in content_type:
        return {}

    boundary = content_type.split("boundary=", 1)[1].strip().strip('"')
    content_length = int(handler.headers.get("Content-Length", "0") or 0)
    raw = handler.rfile.read(content_length) if content_length else b""

    marker = ("--" + boundary).encode("utf-8")
    parts = raw.split(marker)
    result: dict[str, Any] = {}

    for part in parts:
        part = part.strip()
        if not part or part == b"--":
            continue

        head, sep, body = part.partition(b"\r\n\r\n")
        if not sep:
            continue
        body = body.rstrip(b"\r\n")

        headers = head.decode("utf-8", errors="ignore").split("\r\n")
        disposition = ""
        for line in headers:
            if line.lower().startswith("content-disposition:"):
                disposition = line
                break
        if not disposition:
            continue

        attrs: dict[str, str] = {}
        for token in disposition.split(";")[1:]:
            token = token.strip()
            if "=" in token:
                k, v = token.split("=", 1)
                attrs[k.strip()] = v.strip().strip('"')

        name = attrs.get("name")
        if not name:
            continue

        if "filename" in attrs:
            result[name] = {
                "filename": attrs.get("filename", ""),
                "content": body,
            }
        else:
            result[name] = body.decode("utf-8", errors="ignore")

    return result


def json_response(handler: SimpleHTTPRequestHandler, data: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def check_admin_auth(handler: SimpleHTTPRequestHandler) -> bool:
    token = handler.headers.get("X-Admin-Token", "")
    return bool(token) and token == ADMIN_TOKEN


class WishStoneHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/venues":
            conn = get_conn()
            rows = conn.execute("SELECT id, name, type, city FROM venue WHERE is_active=1").fetchall()
            conn.close()
            venues = [dict(row) for row in rows]
            return json_response(self, {"venues": venues})

        if path.startswith("/api/sessions/"):
            slug = path.split("/api/sessions/", 1)[1]
            conn = get_conn()
            row = conn.execute(
                """
                SELECT s.*, v.name AS venue_name, p.role_name
                FROM blessing_session s
                JOIN venue v ON v.id = s.venue_id
                LEFT JOIN prompt_template p ON p.id = v.prompt_template_id
                WHERE s.blessing_page_slug=?
                """,
                (slug,),
            ).fetchone()
            conn.close()

            if not row:
                return json_response(self, {"error": "session not found"}, status=404)

            session = dict(row)
            return json_response(
                self,
                {
                    "session": {
                        "id": session["id"],
                        "slug": session["blessing_page_slug"],
                        "venue_name": session["venue_name"],
                        "role_name": session.get("role_name") or "守护者",
                        "asr_text": session["asr_text"],
                        "intent": session["intent"],
                        "sub_intent": session["sub_intent"],
                        "emotion": session["emotion"],
                        "safety": session["safety"],
                        "ai_reply_text": session["ai_reply_text"],
                        "user_audio_url": session["user_audio_url"],
                        "ai_reply_audio_url": session["ai_reply_audio_url"],
                        "created_at": session["created_at"],
                    }
                },
            )

        if path == "/api/admin/stats":
            if not check_admin_auth(self):
                return json_response(self, {"error": "unauthorized"}, status=401)
            return self.get_admin_stats()

        if path == "/api/admin/sessions":
            if not check_admin_auth(self):
                return json_response(self, {"error": "unauthorized"}, status=401)
            limit = 50
            if "limit" in query:
                try:
                    limit = max(1, min(200, int(query["limit"][0])))
                except ValueError:
                    limit = 50
            return self.get_admin_sessions(limit=limit)

        if path == "/api/admin/nfc-bindings":
            if not check_admin_auth(self):
                return json_response(self, {"error": "unauthorized"}, status=401)
            return self.get_admin_nfc_bindings()

        if path.startswith("/api/admin/prompts/"):
            if not check_admin_auth(self):
                return json_response(self, {"error": "unauthorized"}, status=401)
            venue_id = path.split("/api/admin/prompts/", 1)[1]
            return self.get_admin_prompt(venue_id=venue_id)

        if path.startswith("/b/"):
            self.path = "/blessing.html"
            return super().do_GET()

        if path == "/admin":
            self.path = "/admin.html"
            return super().do_GET()

        if path.startswith("/media/"):
            media_path = STORAGE_DIR / path.replace("/media/", "", 1)
            if not media_path.exists() or not media_path.is_file():
                self.send_error(404, "Not Found")
                return

            self.send_response(200)
            if media_path.suffix == ".wav":
                ctype = "audio/wav"
            elif media_path.suffix == ".webm":
                ctype = "audio/webm"
            else:
                ctype = "application/octet-stream"
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(media_path.stat().st_size))
            self.end_headers()
            with media_path.open("rb") as f:
                self.wfile.write(f.read())
            return

        if path == "/":
            self.path = "/index.html"

        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/sessions":
            return self.create_session()

        if path == "/api/nfc/bind":
            payload = parse_json_body(self)
            blessing_session_id = payload.get("blessing_session_id", "")
            nfc_uid = payload.get("nfc_uid", "")
            souvenir_sku = payload.get("souvenir_sku", "")

            if not blessing_session_id or not nfc_uid:
                return json_response(self, {"error": "blessing_session_id and nfc_uid are required"}, status=400)

            conn = get_conn()
            session = conn.execute(
                "SELECT id FROM blessing_session WHERE id=?", (blessing_session_id,)
            ).fetchone()
            if not session:
                conn.close()
                return json_response(self, {"error": "session not found"}, status=404)

            bind_id = f"bind-{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO souvenir_nfc_binding(id, blessing_session_id, nfc_uid, souvenir_sku, bind_status, bind_time)
                VALUES (?, ?, ?, ?, 'bound', ?)
                """,
                (bind_id, blessing_session_id, nfc_uid, souvenir_sku, now_iso()),
            )
            conn.commit()
            conn.close()

            return json_response(self, {"binding": {"id": bind_id, "status": "bound"}}, status=201)

        if path.startswith("/api/admin/sessions/") and path.endswith("/review"):
            if not check_admin_auth(self):
                return json_response(self, {"error": "unauthorized"}, status=401)
            session_id = path.split("/api/admin/sessions/", 1)[1].split("/review", 1)[0]
            return self.update_admin_review(session_id=session_id)

        if path.startswith("/api/admin/prompts/"):
            if not check_admin_auth(self):
                return json_response(self, {"error": "unauthorized"}, status=401)
            venue_id = path.split("/api/admin/prompts/", 1)[1]
            return self.update_admin_prompt(venue_id=venue_id)

        json_response(self, {"error": "not found"}, status=404)

    def get_admin_stats(self) -> None:
        conn = get_conn()
        row = conn.execute(
            """
            SELECT
              COUNT(*) AS total_sessions,
              SUM(CASE WHEN safety='pass' THEN 1 ELSE 0 END) AS safe_sessions,
              SUM(CASE WHEN safety!='pass' THEN 1 ELSE 0 END) AS blocked_sessions,
              SUM(CASE WHEN review_status='approved' THEN 1 ELSE 0 END) AS approved_sessions
            FROM blessing_session
            """
        ).fetchone()
        intents = conn.execute(
            """
            SELECT intent, COUNT(*) AS count
            FROM blessing_session
            GROUP BY intent
            ORDER BY count DESC
            LIMIT 8
            """
        ).fetchall()
        conn.close()
        return json_response(
            self,
            {
                "stats": {
                    "total_sessions": row["total_sessions"] or 0,
                    "safe_sessions": row["safe_sessions"] or 0,
                    "blocked_sessions": row["blocked_sessions"] or 0,
                    "approved_sessions": row["approved_sessions"] or 0,
                    "top_intents": [dict(x) for x in intents],
                }
            },
        )

    def get_admin_sessions(self, limit: int) -> None:
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT s.id, s.created_at, s.intent, s.sub_intent, s.emotion, s.safety, s.review_status, s.asr_text,
                   s.ai_reply_text, s.blessing_page_slug, v.name AS venue_name
            FROM blessing_session s
            JOIN venue v ON v.id = s.venue_id
            ORDER BY s.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()
        return json_response(self, {"sessions": [dict(row) for row in rows]})

    def get_admin_nfc_bindings(self) -> None:
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT n.id, n.nfc_uid, n.souvenir_sku, n.bind_status, n.bind_time, n.blessing_session_id,
                   s.blessing_page_slug
            FROM souvenir_nfc_binding n
            JOIN blessing_session s ON s.id = n.blessing_session_id
            ORDER BY n.bind_time DESC
            LIMIT 100
            """
        ).fetchall()
        conn.close()
        return json_response(self, {"bindings": [dict(row) for row in rows]})

    def get_admin_prompt(self, venue_id: str) -> None:
        conn = get_conn()
        row = conn.execute(
            """
            SELECT p.id, p.venue_id, p.role_name, p.system_prompt, p.response_style, p.forbidden_rules, p.version
            FROM prompt_template p
            WHERE p.venue_id=?
            """,
            (venue_id,),
        ).fetchone()
        conn.close()
        if not row:
            return json_response(self, {"error": "prompt not found"}, status=404)
        return json_response(self, {"prompt": dict(row)})

    def update_admin_prompt(self, venue_id: str) -> None:
        payload = parse_json_body(self)
        required = ["role_name", "system_prompt", "response_style", "forbidden_rules"]
        if any(not str(payload.get(key, "")).strip() for key in required):
            return json_response(self, {"error": "missing required prompt fields"}, status=400)

        conn = get_conn()
        row = conn.execute("SELECT id, version FROM prompt_template WHERE venue_id=?", (venue_id,)).fetchone()
        if not row:
            conn.close()
            return json_response(self, {"error": "prompt not found"}, status=404)

        old_version = row["version"]
        if old_version.startswith("v") and old_version[1:].isdigit():
            version = f"v{int(old_version[1:]) + 1}"
        else:
            version = f"{old_version}-next"

        conn.execute(
            """
            UPDATE prompt_template
            SET role_name=?, system_prompt=?, response_style=?, forbidden_rules=?, version=?
            WHERE venue_id=?
            """,
            (
                payload["role_name"].strip(),
                payload["system_prompt"].strip(),
                payload["response_style"].strip(),
                payload["forbidden_rules"].strip(),
                version,
                venue_id,
            ),
        )
        conn.commit()
        conn.close()
        return json_response(self, {"ok": True, "version": version})

    def update_admin_review(self, session_id: str) -> None:
        payload = parse_json_body(self)
        review_status = str(payload.get("review_status", "")).strip()
        if review_status not in {"pending", "approved", "blocked"}:
            return json_response(self, {"error": "review_status must be pending/approved/blocked"}, status=400)
        conn = get_conn()
        row = conn.execute("SELECT id FROM blessing_session WHERE id=?", (session_id,)).fetchone()
        if not row:
            conn.close()
            return json_response(self, {"error": "session not found"}, status=404)
        conn.execute("UPDATE blessing_session SET review_status=? WHERE id=?", (review_status, session_id))
        conn.commit()
        conn.close()
        return json_response(self, {"ok": True, "review_status": review_status})

    def create_session(self) -> None:
        ctype = self.headers.get_content_type()

        venue_id = "venue-liangzhu"
        device_id = "device-demo-001"
        user_text = ""
        audio_public_url = ""

        if ctype == "multipart/form-data":
            form = parse_multipart_body(self)
            venue_id = form.get("venue_id", venue_id)
            device_id = form.get("device_id", device_id)
            user_text = form.get("user_text", "")

            audio_file = form.get("audio")
            if isinstance(audio_file, dict) and audio_file.get("content"):
                filename = f"{uuid.uuid4().hex}.webm"
                path = USER_AUDIO_DIR / filename
                with path.open("wb") as f:
                    f.write(audio_file["content"])
                audio_public_url = f"/media/user_audio/{filename}"

        elif ctype == "application/json":
            payload = parse_json_body(self)
            venue_id = payload.get("venue_id", venue_id)
            device_id = payload.get("device_id", device_id)
            user_text = payload.get("user_text", "")

        asr_text, confidence = mock_asr_text(user_text)
        intent_result = detect_intent(asr_text)
        emotion = detect_emotion(asr_text)
        safety = detect_safety(asr_text)

        conn = get_conn()
        venue = conn.execute(
            """
            SELECT v.id, v.name, p.role_name
            FROM venue v
            LEFT JOIN prompt_template p ON p.id = v.prompt_template_id
            WHERE v.id=?
            """,
            (venue_id,),
        ).fetchone()
        if not venue:
            conn.close()
            return json_response(self, {"error": "venue not found"}, status=404)

        ai_reply = generate_reply(
            venue_name=venue["name"],
            role_name=venue["role_name"] or "守护者",
            asr_text=asr_text,
            intent=intent_result["intent"],
            emotion=emotion,
            safety=safety,
        )

        session_id = f"sess-{uuid.uuid4().hex[:12]}"
        slug = uuid.uuid4().hex[:8]
        ai_audio_url = synthesize_placeholder_audio(session_id, ai_reply)
        page_url = f"/b/{slug}"

        conn.execute(
            """
            INSERT INTO blessing_session(
                id, venue_id, device_id, user_audio_url, asr_text, intent, sub_intent, emotion, safety,
                ai_reply_text, ai_reply_audio_url, blessing_page_slug, qr_code_url, created_at, review_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                venue_id,
                device_id,
                audio_public_url,
                asr_text,
                intent_result["intent"],
                intent_result["sub_intent"],
                emotion,
                safety,
                ai_reply,
                ai_audio_url,
                slug,
                page_url,
                now_iso(),
                "approved" if safety == "pass" else "blocked",
            ),
        )
        conn.commit()
        conn.close()

        return json_response(
            self,
            {
                "session": {
                    "id": session_id,
                    "slug": slug,
                    "venue_id": venue_id,
                    "device_id": device_id,
                    "asr": {
                        "text": asr_text,
                        "confidence": confidence,
                        "segments": [],
                    },
                    "intent": {
                        "intent": intent_result["intent"],
                        "sub_intent": intent_result["sub_intent"],
                        "emotion": emotion,
                        "safety": safety,
                    },
                    "ai_reply_text": ai_reply,
                    "user_audio_url": audio_public_url,
                    "ai_reply_audio_url": ai_audio_url,
                    "blessing_page_url": page_url,
                }
            },
            status=201,
        )


def run() -> None:
    USER_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    AI_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    init_db()

    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), WishStoneHandler)
    print(f"WishStone server running: http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run()
