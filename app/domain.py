"""Local, deterministic wish classification and venue-specific souvenir matching."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(os.environ.get("VENUE_CONFIG", str(Path(__file__).resolve().parent.parent / "examples/venues/liangzhu.json")))


def load_catalog(path: Path) -> dict[str, Any]:
    catalog = json.loads(path.read_text())
    if not isinstance(catalog, dict) or not isinstance(catalog.get("venues"), list) or not catalog["venues"]:
        raise ValueError("场景配置需要非空 venues 数组")
    ids, devices = set(), set()
    for venue in catalog["venues"]:
        required = ["id", "name", "type", "city", "theme", "description", "role_name", "motif", "device_id"]
        if not isinstance(venue, dict) or any(not isinstance(venue.get(key), str) or not venue[key].strip() for key in required):
            raise ValueError("场景缺少必填文本字段，请参照 examples/venues/template.json")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", venue["id"]) or not re.fullmatch(r"[A-Za-z0-9_-]+", venue["device_id"]):
            raise ValueError("场馆和装置 ID 只能包含字母、数字、下划线和连字符")
        if venue["id"] in ids or venue["device_id"] in devices:
            raise ValueError("场馆与装置 ID 不可重复")
        ids.add(venue["id"]); devices.add(venue["device_id"])
        souvenirs = venue.get("souvenirs")
        if not isinstance(souvenirs, list) or not souvenirs:
            raise ValueError("每个场景至少需要一个纪念品")
        skus = set()
        for item in souvenirs:
            fields = ["sku", "name", "subtitle", "description", "motif", "material"]
            if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key].strip() for key in fields):
                raise ValueError("纪念品缺少必填文本字段")
            if item["sku"] in skus:
                raise ValueError("同场景纪念品 SKU 不可重复")
            skus.add(item["sku"])
            if not isinstance(item.get("intents"), list) or not item["intents"] or any(not isinstance(label, str) or not label for label in item["intents"]):
                raise ValueError("纪念品 intents 需要非空类别数组")
            if not isinstance(item.get("design_parameters", {}), dict):
                raise ValueError("design_parameters 应为设计参数对象")
            if not isinstance(item.get("customizable"), bool):
                raise ValueError("纪念品 customizable 需要 true 或 false")
        rules = venue.get("intent_rules", {})
        if not isinstance(rules, dict) or any(not label or not isinstance(words, list) or not words or any(not isinstance(word, str) or not word for word in words) for label, words in rules.items()):
            raise ValueError("intent_rules 应为类别到非空关键词数组")
        if not isinstance(venue.get("blessings", {}), dict) or any(not isinstance(value, str) for value in venue.get("blessings", {}).values()):
            raise ValueError("blessings 应为类别到祝福文本")
    catalog.setdefault("notice", "场景配置由部署者提供。")
    return catalog


CATALOG = load_catalog(CONFIG_PATH)
VENUES = {venue["id"]: venue for venue in CATALOG["venues"]}
DEFAULT_VENUE_ID = next(iter(VENUES))
RULES = {
    "学业": ["考研", "上岸", "考试", "学业", "读书", "升学", "学习", "论文", "毕业", "高考", "录取"],
    "事业": ["工作", "升职", "事业", "面试", "创业", "项目", "求职", "同事", "职场"],
    "爱情": ["姻缘", "爱情", "对象", "脱单", "感情", "婚姻", "爱人", "恋爱"],
    "健康": ["健康", "平安", "身体", "康复", "生病", "手术", "病痛", "无恙"],
    "家庭": ["家人", "父母", "妈妈", "爸爸", "母亲", "父亲", "孩子", "团圆", "家庭"],
    "财运": ["财运", "收入", "财富", "机缘", "生意", "财源", "积蓄"],
}
REPLIES = {
    "学业": "愿你所学如玉初琢，日日有进。每一次专注，都是离心中方向更近一步。",
    "事业": "愿你行路稳健，所付出的心力，在时光里沉淀为收获，也记得为自己留一点从容。",
    "爱情": "愿你被真诚理解，也自在地表达自己。让相遇慢慢发生，让相伴温柔长久。",
    "健康": "愿你与所牵挂的人，身心安宁，晨昏皆稳。在寻常日子里，好好照顾自己。",
    "家庭": "愿相聚时有笑语，远行时有牵挂。把关心说出口，让温暖留在每一个日常。",
    "财运": "愿你的耕耘慢慢丰盈，也愿你珍惜已拥有的，在踏实的生活里发现新的可能。",
    "人生": "愿你在前行中渐明方向，把每一步都走成心安与笃定，也允许自己偶尔停一停。",
}


def classify(text: str, venue_id: str | None = None) -> dict[str, Any]:
    """Scores are keyword evidence counts, never calibrated model confidence."""
    rules = VENUES.get(venue_id, {}).get("intent_rules", RULES)
    scores = []
    for label, words in rules.items():
        matched = [word for word in words if word in text]
        if matched:
            scores.append({"label": label, "score": len(matched), "matched_keywords": matched})
    scores.sort(key=lambda item: item["score"], reverse=True)
    if not scores:
        scores = [{"label": "人生", "score": 0, "matched_keywords": []}]
    safety = "blocked" if any(word in text.lower() for word in ["自杀", "轻生", "炸弹", "毒品", "恐怖袭击", "terror"]) else "pass"
    emotion = "紧张与期待" if any(word in text for word in ["焦虑", "紧张", "担心", "害怕"]) else "期待与牵挂"
    if any(word in text for word in ["感谢", "感恩"]):
        emotion = "感恩与平和"
    return {
        "intent": scores[0]["label"], "sub_intent": "心愿", "labels": scores,
        "emotion": emotion, "safety": safety, "provider": "local-rules",
        "needs_confirmation": scores[0]["score"] == 0 or (len(scores) > 1 and scores[0]["score"] == scores[1]["score"]),
    }


def match_souvenirs(venue_id: str, intent: dict[str, Any]) -> list[dict[str, Any]]:
    labels = {item["label"] for item in intent["labels"]}
    ranked = []
    for souvenir in VENUES[venue_id]["souvenirs"]:
        overlap = labels.intersection(souvenir["intents"])
        score = len(overlap) + (2 if intent["intent"] in souvenir["intents"] else 0)
        ranked.append({**souvenir, "match_score": score, "reason": f"呼应你的{'、'.join(sorted(overlap))}心愿" if overlap else "也可以选择这一份场馆纪念"})
    return sorted(ranked, key=lambda item: item["match_score"], reverse=True)


def reply_for(venue_id: str, intent: dict[str, Any]) -> str:
    if intent["safety"] != "pass":
        return "愿你此刻有人陪伴，平安安稳。如果正面临危险，请及时向身边可信的人或当地紧急服务求助。"
    venue = VENUES[venue_id]
    replies = venue.get("blessings", REPLIES)
    return replies.get(intent["intent"], replies.get("人生", REPLIES["人生"])) + " " + venue.get("blessing_suffix", "愿这份心意，被岁月温柔照见。")


def normalize_uid(value: str) -> str:
    compact = re.sub(r"[:\-\s]", "", value).upper()
    if not re.fullmatch(r"(?:[0-9A-F]{2}){4,10}", compact):
        raise ValueError("NFC UID 应为 4–10 字节的十六进制编号")
    return ":".join(compact[i:i + 2] for i in range(0, len(compact), 2))


def make_design_brief(venue_id: str, souvenir: dict[str, Any], intent: str) -> dict[str, Any]:
    venue = VENUES[venue_id]
    return {
        "status": "brief_ready", "provider": "not-configured", "model_url": None,
        "prompt": f"为{venue['name']}设计{souvenir['subtitle']}，提取{venue['motif']}的抽象几何意象，表达{intent}心愿。圆润边缘，可平放，预留 NFC 芯片腔体；无宗教功效承诺，无用户个人信息。",
        "parameters": {"size_mm": [45, 45, 12], "nfc_cavity_mm": [27, 27, 2], "material": souvenir["material"], "output_formats": ["glb", "stl"], **souvenir.get("design_parameters", {})},
        "notice": "仅为设计任务，未调用 3D 生成模型；尺寸、结构、打印可行性和 NFC 天线表现需实物验证。",
    }
