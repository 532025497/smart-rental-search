# -*- coding: utf-8 -*-
"""SQLite 房源库、手动文本解析与区域价格统计。"""
import hashlib
import os
import re
import sqlite3
import threading
from datetime import date, datetime
from urllib.parse import urlparse


PRICE_PATTERNS = [
    re.compile(r"(?:月租|租金|房租)\s*[:：]?\s*[¥￥]?\s*(\d{3,6})(?:\s*元)?"),
    re.compile(r"[¥￥]\s*(\d{3,6})(?:\s*/?\s*月)?"),
    re.compile(r"(\d{3,6})\s*(?:元|块)(?:\s*/?\s*月|\s*每月)"),
]


def _clean_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _parse_price(text: str):
    for pattern in PRICE_PATTERNS:
        match = pattern.search(text)
        if match:
            price = int(match.group(1))
            if 300 <= price <= 100000:
                return price
    return None


def _detect_lease_term(text: str) -> str:
    if re.search(r"短租|日租|周租|可短租|租期[一二三四五六1-6个\s]*月", text):
        return "短租"
    if re.search(r"长租|年租|一年起租|至少一年|押一付三", text):
        return "长租"
    return "未知"


def _detect_room_type(text: str) -> str:
    for value in ("整租", "合租", "主卧", "次卧", "单间", "一居室"):
        if value in text:
            return "整租" if value == "一居室" else value
    return "未知"


def _detect_listing_type(text: str) -> str:
    for value in ("转租", "房东直租", "直租", "找室友", "个人房源"):
        if value in text:
            return value
    if "中介" in text or "经纪人" in text:
        return "中介"
    return "未知"


def _detect_personal(text: str):
    if re.search(r"个人|房东直租|转租|找室友|无中介费", text):
        return True
    if re.search(r"中介|经纪人|服务费|渠道费|咨询顾问", text):
        return False
    return None


def _safe_url(value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("来源链接必须是 http 或 https 地址")
    return value


def _percentile(values, fraction: float):
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight)


class ListingStore:
    """持久化房源并提供区域、租期、房型维度的价格统计。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS listings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fingerprint TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    raw_text TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    source_platform TEXT NOT NULL DEFAULT 'manual',
                    city TEXT NOT NULL,
                    district TEXT NOT NULL DEFAULT '',
                    neighborhood TEXT NOT NULL DEFAULT '',
                    station TEXT NOT NULL DEFAULT '',
                    price_monthly INTEGER NOT NULL,
                    lease_term TEXT NOT NULL DEFAULT '未知',
                    room_type TEXT NOT NULL DEFAULT '未知',
                    listing_type TEXT NOT NULL DEFAULT '未知',
                    is_personal INTEGER,
                    published_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_city ON listings(city)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_station ON listings(station)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_price ON listings(price_monthly)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_published ON listings(published_at)")

    def normalize(self, payload: dict) -> dict:
        raw_text = str(payload.get("raw_text") or payload.get("description") or "").strip()
        title = _clean_text(payload.get("title"))
        if not title and raw_text:
            title = _clean_text(raw_text.splitlines()[0])[:80]
        title = title or "手动导入房源"

        city = _clean_text(payload.get("city")) or "北京"
        district = _clean_text(payload.get("district"))
        neighborhood = _clean_text(payload.get("neighborhood"))
        station = _clean_text(payload.get("station") or payload.get("area"))
        source_url = _safe_url(payload.get("source_url"))
        source_platform = _clean_text(payload.get("source_platform")) or "manual"

        combined = "\n".join((title, raw_text))
        supplied_price = payload.get("price_monthly")
        try:
            price = int(supplied_price) if supplied_price not in (None, "") else None
        except (TypeError, ValueError):
            raise ValueError("月租必须是数字")
        price = price or _parse_price(combined)
        if not price or price < 300 or price > 100000:
            raise ValueError("未识别到有效月租，请填写 300-100000 元之间的价格")

        lease_term = _clean_text(payload.get("lease_term"))
        if lease_term not in ("短租", "长租", "未知"):
            lease_term = "未知"
        if lease_term == "未知":
            lease_term = _detect_lease_term(combined)

        room_type = _clean_text(payload.get("room_type"))
        if not room_type or room_type == "未知":
            room_type = _detect_room_type(combined)

        listing_type = _clean_text(payload.get("listing_type"))
        if not listing_type:
            listing_type = _detect_listing_type(combined)

        personal = payload.get("is_personal")
        if isinstance(personal, str):
            personal = personal.lower() in ("1", "true", "yes", "on")
        if personal is None:
            personal = _detect_personal(combined)

        published_at = _clean_text(payload.get("published_at")) or date.today().isoformat()
        try:
            datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("发布时间格式无效，请使用 YYYY-MM-DD")

        fingerprint_base = source_url or "|".join((title, raw_text, city, station, str(price)))
        fingerprint = hashlib.sha256(fingerprint_base.encode("utf-8")).hexdigest()
        now = datetime.now().isoformat(timespec="seconds")
        return {
            "fingerprint": fingerprint,
            "title": title[:160],
            "raw_text": raw_text,
            "source_url": source_url,
            "source_platform": source_platform[:40],
            "city": city[:40],
            "district": district[:80],
            "neighborhood": neighborhood[:120],
            "station": station[:80],
            "price_monthly": price,
            "lease_term": lease_term,
            "room_type": room_type[:40],
            "listing_type": listing_type[:40],
            "is_personal": None if personal is None else int(bool(personal)),
            "published_at": published_at,
            "created_at": now,
            "updated_at": now,
        }

    def save(self, payload: dict) -> dict:
        item = self.normalize(payload)
        columns = list(item.keys())
        placeholders = ", ".join("?" for _ in columns)
        update_columns = [name for name in columns if name not in ("fingerprint", "created_at")]
        update_sql = ", ".join(f"{name}=excluded.{name}" for name in update_columns)
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM listings WHERE fingerprint=?", (item["fingerprint"],)
            ).fetchone()
            conn.execute(
                f"INSERT INTO listings ({', '.join(columns)}) VALUES ({placeholders}) "
                f"ON CONFLICT(fingerprint) DO UPDATE SET {update_sql}",
                [item[name] for name in columns],
            )
            row = conn.execute(
                "SELECT * FROM listings WHERE fingerprint=?", (item["fingerprint"],)
            ).fetchone()
        result = self._row_to_dict(row)
        result["duplicate"] = existing is not None
        return result

    @staticmethod
    def _row_to_dict(row) -> dict:
        item = dict(row)
        item["is_personal"] = None if row["is_personal"] is None else bool(row["is_personal"])
        item["confidence"] = 0.8 if item["is_personal"] is True else 0.55
        item["rental_subtype"] = item.pop("listing_type")
        item["address_raw"] = item["station"] or item["neighborhood"] or item["district"]
        item["attempts"] = 0
        item["is_rental"] = True
        return item

    def _where(self, city="", area="", lease_term="", room_type="",
               personal_only=False, budget_min=None, budget_max=None,
               recent_days=60):
        clauses = ["date(published_at) >= date('now', ?)"]
        params = [f"-{int(recent_days)} days"]
        if city:
            clauses.append("city = ?")
            params.append(city)
        if area:
            clauses.append("(station LIKE ? OR neighborhood LIKE ? OR district LIKE ? OR raw_text LIKE ?)")
            token = f"%{area}%"
            params.extend([token, token, token, token])
        if lease_term and lease_term != "不限":
            clauses.append("lease_term = ?")
            params.append(lease_term)
        if room_type and room_type != "不限":
            clauses.append("room_type = ?")
            params.append(room_type)
        if personal_only:
            clauses.append("is_personal = 1")
        if budget_min:
            clauses.append("price_monthly >= ?")
            params.append(int(budget_min))
        if budget_max:
            clauses.append("price_monthly <= ?")
            params.append(int(budget_max))
        return " AND ".join(clauses), params

    def list(self, limit=100, **filters) -> list:
        where, params = self._where(**filters)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM listings WHERE {where} "
                "ORDER BY date(published_at) DESC, id DESC LIMIT ?",
                params + [min(max(int(limit), 1), 500)],
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def list_for_stations(self, station_names, **filters) -> list:
        found = {}
        for station in station_names:
            for item in self.list(area=station, limit=100, **filters):
                found[item["id"]] = item
        return sorted(found.values(), key=lambda item: item["published_at"], reverse=True)

    def price_stats(self, **filters) -> dict:
        listings = self.list(limit=500, **filters)
        prices = [item["price_monthly"] for item in listings]
        count = len(prices)
        if not prices:
            return {
                "sample_count": 0,
                "median": None,
                "q25": None,
                "q75": None,
                "minimum": None,
                "maximum": None,
                "confidence": "数据不足",
            }
        confidence = "较高" if count >= 15 else "中等" if count >= 5 else "数据不足"
        return {
            "sample_count": count,
            "median": _percentile(prices, 0.5),
            "q25": _percentile(prices, 0.25),
            "q75": _percentile(prices, 0.75),
            "minimum": min(prices),
            "maximum": max(prices),
            "confidence": confidence,
        }
