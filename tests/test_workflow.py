import concurrent.futures
import importlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "hardware")]
import server
from domain import classify, match_souvenirs, load_catalog, VENUES, reply_for
from ntag215 import NTAG215Writer, encode_uri_tlv


class HTTPWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.data = Path(cls.temp.name)
        cls.patch = patch.multiple(server, DATA_DIR=cls.data, STORAGE_DIR=cls.data / "storage", USER_AUDIO_DIR=cls.data / "storage/user_audio", DB_PATH=cls.data / "wishstone.db", ADMIN_TOKEN="test-admin", DEVICE_TOKEN="test-device")
        cls.patch.start()
        cls.env = patch.dict(os.environ, {"PUBLIC_BASE_URL": "https://example.test", "ASR_HTTP_URL": ""})
        cls.env.start()
        server.init_db()
        class QuietHandler(server.WishStoneHandler):
            def log_message(self, *args): pass
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        cls.url = f"http://127.0.0.1:{cls.http.server_port}"
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True); cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.thread.join(); cls.env.stop(); cls.patch.stop(); cls.temp.cleanup()

    def request(self, path, data=None, headers=None, raw=None):
        body = json.dumps(data).encode() if data is not None else raw
        headers = {"Content-Type": "application/json", **(headers or {})}
        try:
            with urlopen(Request(self.url + path, data=body, headers=headers)) as res:
                return res.status, json.loads(res.read())
        except HTTPError as error:
            try:
                return error.code, json.loads(error.read())
            finally:
                error.close()

    def wish(self, text="希望考试顺利，也希望妈妈身体健康"):
        status, data = self.request("/api/sessions", {"user_text": text})
        self.assertEqual(status, 201, data)
        return data["session"]

    def test_text_multilabel_and_matching(self):
        wish = self.wish()
        self.assertEqual({"学业", "健康", "家庭"}, {i["label"] for i in wish["intent"]["labels"]})
        self.assertEqual(wish["asr"]["provider"], "user-text")
        self.assertIsNone(wish["asr"]["confidence"])
        self.assertIsNone(wish["ai_reply_audio_url"])
        self.assertEqual(wish["selected_souvenir"]["sku"], "LZ-BI")
        self.assertEqual(self.request("/api/sessions/" + wish["slug"])[0], 200)

    def test_empty_and_bad_json_are_rejected(self):
        self.assertEqual(self.request("/api/sessions", {})[0], 400)
        self.assertEqual(self.request("/api/sessions", raw=b"{")[0], 400)
        self.assertEqual(self.request("/api/sessions", raw=b"[]")[0], 400)
        self.assertEqual(self.request("/api/sessions", {"user_text": 123})[0], 400)

    def test_device_venue_mismatch_and_unknown_venue(self):
        self.assertEqual(self.request("/api/sessions", {"user_text": "平安", "device_id": "other"})[0], 400)
        self.assertEqual(self.request("/api/sessions", {"user_text": "平安", "venue_id": "other"})[0], 404)

    def test_audio_unconfigured_never_invents_transcript(self):
        boundary = "test-boundary"
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="a.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + b"audio\x00\r\n" + f"\r\n--{boundary}--\r\n".encode())
        status, data = self.request("/api/sessions", raw=body, headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
        self.assertEqual(status, 503, data)
        self.assertNotIn("session", data)

    def test_audio_adapter_preserves_binary_and_reports_provider(self):
        captured = []
        class ASR(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                captured.append(server.parse_body(self)["audio"]["content"])
                server.json_response(self, {"text": "愿家人健康平安", "provider": "sensevoice-sherpa-onnx"})
        service = ThreadingHTTPServer(("127.0.0.1", 0), ASR)
        thread = threading.Thread(target=service.serve_forever, daemon=True); thread.start()
        audio = b"RIFF\x00\x00binary\r\n"
        boundary = "audio-boundary"
        body = f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="x.wav"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + audio + f"\r\n--{boundary}--\r\n".encode()
        try:
            with patch.dict(os.environ, {"ASR_HTTP_URL": f"http://127.0.0.1:{service.server_port}/transcribe"}):
                status, data = self.request("/api/sessions", raw=body, headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
            self.assertEqual(status, 201, data)
            self.assertEqual(captured, [audio])
            self.assertEqual(data["session"]["asr"]["provider"], "sensevoice-sherpa-onnx")
            self.assertEqual(list((self.data / "storage/user_audio").iterdir()), [])
        finally:
            service.shutdown(); service.server_close(); thread.join()

    def test_nfc_manual_is_idempotent_and_not_written(self):
        wish = self.wish()
        body = {"blessing_session_id": wish["id"], "nfc_uid": "04AABB01020304"}
        first = self.request("/api/nfc/bind", body)[1]["binding"]
        second = self.request("/api/nfc/bind", body)[1]["binding"]
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["status"], "registered")
        other = self.wish()
        self.assertEqual(self.request("/api/nfc/bind", {**body, "blessing_session_id": other["id"]})[0], 409)
        self.assertEqual(self.request(f"/api/sessions/{wish['slug']}/souvenir", {"souvenir_sku": "LZ-CONG"})[0], 409)

    def test_nfc_concurrent_claims_have_one_winner(self):
        wishes = [self.wish(), self.wish()]
        def bind(wish):
            return self.request("/api/nfc/bind", {"blessing_session_id": wish["id"], "nfc_uid": "04CCDD01020304"})[0]
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            self.assertEqual(sorted(pool.map(bind, wishes)), [200, 409])

    def test_hardware_receipt_requires_device_auth_and_matching_url(self):
        wish = self.wish()
        body = {"blessing_session_id": wish["id"], "nfc_uid": "04DDEE01020304", "method": "pn532", "readback_url": "wrong"}
        self.assertEqual(self.request("/api/nfc/bind", body)[0], 401)
        headers = {"X-Device-Token": "test-device"}
        self.assertEqual(self.request("/api/nfc/bind", body, headers)[0], 400)
        nfc = self.request(f"/api/sessions/{wish['slug']}/nfc")[1]["nfc"]
        body["readback_url"] = nfc["url"]
        status, data = self.request("/api/nfc/bind", body, headers)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["binding"]["status"], "device_verified")

    def test_design_job_idempotent_and_explicitly_brief_only(self):
        wish = self.wish()
        first = self.request("/api/design-jobs", {"slug": wish["slug"]})[1]["job"]
        second = self.request("/api/design-jobs", {"slug": wish["slug"]})[1]["job"]
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["status"], "brief_ready")
        self.assertIsNone(first["model_url"])

    def test_review_revokes_public_record_and_nfc(self):
        wish = self.wish()
        status, _ = self.request(f"/api/admin/sessions/{wish['id']}/review", {"review_status": "blocked"}, {"X-Admin-Token": "test-admin"})
        self.assertEqual(status, 200)
        self.assertEqual(self.request("/api/sessions/" + wish["slug"])[0], 403)
        self.assertEqual(self.request(f"/api/sessions/{wish['slug']}/nfc")[0], 403)

    def test_admin_and_origin_protection(self):
        self.assertEqual(self.request("/api/admin/stats")[0], 401)
        self.assertEqual(self.request("/api/sessions", {"user_text": "平安"}, {"Origin": "https://unrelated.test"})[0], 403)

    def test_catalog_sku_scope(self):
        wish = self.wish()
        self.assertEqual(self.request(f"/api/sessions/{wish['slug']}/souvenir", {"souvenir_sku": "UNKNOWN"})[0], 400)
        status, data = self.request(f"/api/sessions/{wish['slug']}/souvenir", {"souvenir_sku": "LZ-CONG"})
        self.assertEqual(status, 200, data)
        self.assertEqual(data["session"]["selected_souvenir"]["sku"], "LZ-CONG")


class FakeReader:
    def __init__(self):
        self.uid = bytes.fromhex("04AABBCCDDEEFF")
        self.memory = bytearray(540)
        self.memory[12:16] = b"\xe1\x10\x3e\x00"
        self.memory[16:20] = b"\x03\x00\xfe\x00"
        self.writes = []
        self.corrupt_readback = False
    def read_passive_target(self, timeout): return self.uid
    def ntag2xx_read_block(self, page):
        data = bytes(self.memory[page*4:page*4+4])
        if self.corrupt_readback and self.writes and page == 5:
            return b"oops"
        return data
    def ntag2xx_write_block(self, page, data):
        self.writes.append(page)
        self.memory[page*4:page*4+4] = data
        return True


class NTAGProtocol(unittest.TestCase):
    def test_uri_payload_and_capacity(self):
        tlv = encode_uri_tlv("https://example.test/b/abc")
        self.assertEqual(tlv[0], 3)
        self.assertIn(b"\x55\x04example.test/b/abc", tlv)
        with self.assertRaises(ValueError): encode_uri_tlv("https://example.test/" + "x"*600)
        extended = encode_uri_tlv("https://example.test/" + "x"*280)
        self.assertEqual(extended[1], 255)
        self.assertEqual(extended[4], 0xC1)

    def test_write_readback_and_no_config_mutation(self):
        reader = FakeReader(); writer = NTAG215Writer(reader)
        reserved = []
        receipt = writer.write_url("https://example.test/b/abc", reserve=reserved.append)
        self.assertEqual(receipt["status"], "readback_verified")
        self.assertEqual(reserved, [receipt["nfc_uid"]])
        self.assertEqual(reader.writes[0], 4)
        self.assertEqual(reader.writes[-1], 4)
        self.assertTrue(all(4 <= page < 128 for page in reader.writes))
        reader.writes.clear()
        writer.write_url("https://example.test/b/abc")
        self.assertEqual(reader.writes, [])

    def test_existing_content_and_wrong_tag_are_rejected(self):
        reader = FakeReader(); reader.memory[16:20] = b"data"
        with self.assertRaises(ValueError): NTAG215Writer(reader).write_url("https://example.test")
        self.assertEqual(reader.writes, [])
        reader = FakeReader(); reader.memory[14] = 0x12
        with self.assertRaises(ValueError): NTAG215Writer(reader).write_url("https://example.test")

    def test_bad_readback_never_reports_success(self):
        reader = FakeReader(); reader.corrupt_readback = True
        with self.assertRaises(IOError): NTAG215Writer(reader).write_url("https://example.test/b/abc")


class Configuration(unittest.TestCase):
    def test_custom_scene_categories_and_souvenir_mapping(self):
        template = load_catalog(ROOT / "examples/venues/template.json")
        venue = template["venues"][0]
        with patch.dict(VENUES, {venue["id"]: venue}, clear=True):
            intent = classify("希望毕业顺利，愿家人平安", venue["id"])
            self.assertEqual({item["label"] for item in intent["labels"]}, {"成长", "平安"})
            self.assertEqual(match_souvenirs(venue["id"], intent)[0]["sku"], "MY-STONE-001")
            self.assertIn("愿你与牵挂的人安稳相伴", reply_for(venue["id"], intent))

    def test_duplicate_scene_identity_fails_at_startup(self):
        template = json.loads((ROOT / "examples/venues/template.json").read_text())
        template["venues"] *= 2
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(json.dumps(template))
            with self.assertRaises(ValueError): load_catalog(path)


class Migration(unittest.TestCase):
    def test_v1_backup_and_records_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.multiple(server, DATA_DIR=root, STORAGE_DIR=root/"storage", USER_AUDIO_DIR=root/"storage/user_audio", DB_PATH=root/"wishstone.db"):
                server.init_db()
                with server.get_conn() as conn:
                    conn.execute("ALTER TABLE blessing_session DROP COLUMN metadata_json")
                    conn.execute("ALTER TABLE blessing_session DROP COLUMN souvenir_sku")
                    conn.execute("UPDATE venue SET name='保留的自定义名称'")
                    conn.execute("INSERT INTO blessing_session VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        ("legacy-session", "venue-liangzhu", "device-demo-001", "", "保留的心愿", "人生", "方向", "期待", "pass", "保留的祝福", "", "legacy-slug", "", "2026-01-01", "approved"))
                    conn.execute("INSERT INTO souvenir_nfc_binding VALUES (?, ?, ?, ?, ?, ?)",
                        ("legacy-bind", "legacy-session", "04:11:22:33:44:55:66", "old-sku", "bound", "2026-01-01"))
                server.init_db(); server.init_db()
                backups = list((root/"backups").glob("*.db"))
                self.assertEqual(len(backups), 1)
                with server.get_conn() as conn:
                    self.assertEqual(conn.execute("SELECT name FROM venue").fetchone()[0], "保留的自定义名称")
                    self.assertEqual(conn.execute("SELECT asr_text FROM blessing_session WHERE id='legacy-session'").fetchone()[0], "保留的心愿")
                    self.assertEqual(conn.execute("SELECT bind_status FROM souvenir_nfc_binding WHERE id='legacy-bind'").fetchone()[0], "bound")
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM nfc_tag_claim").fetchone()[0], 1)
                    self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")


if __name__ == "__main__": unittest.main()
