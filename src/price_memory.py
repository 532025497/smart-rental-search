# -*- coding: utf-8 -*-
"""区域房价记忆库 — 持久化小红书爬取+LLM兜底的各区域价格分布

存储两类来源:
    - crawler: 从小红书房价分布帖中提取
    - llm:     LLM(点点)提供的知识性大致房价

查询时优先 crawler, 不足时用 llm 兜底。
"""
import os
import sqlite3
import threading
from datetime import datetime


class PriceMemory:
    """区域房价记忆库"""

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
                CREATE TABLE IF NOT EXISTS price_distribution (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    city TEXT NOT NULL,
                    district TEXT NOT NULL,
                    price_min INTEGER,
                    price_max INTEGER,
                    price_avg INTEGER,
                    unit TEXT NOT NULL DEFAULT '元/月',
                    note TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'crawler',
                    source_url TEXT NOT NULL DEFAULT '',
                    confidence REAL DEFAULT 0.5,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_price_city "
                "ON price_distribution(city, district)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_price_source "
                "ON price_distribution(source)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS station_price_reference (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    city TEXT NOT NULL,
                    station TEXT NOT NULL,
                    price_start INTEGER NOT NULL,
                    unit TEXT NOT NULL DEFAULT '元/月',
                    room_type TEXT NOT NULL DEFAULT '合租/单间',
                    source TEXT NOT NULL DEFAULT 'user_image',
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    UNIQUE(city, station, source)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_station_price "
                "ON station_price_reference(city, station)"
            )

    def save(self, city: str, district: str,
             price_min=None, price_max=None, price_avg=None,
             note="", source="crawler", source_url="",
             confidence=0.5) -> dict:
        """写入一条区域价格。同城同区域已存在则更新。
        crawler来源优先覆盖llm来源; llm不覆盖crawler。
        """
        if source == "llm" and self._has_crawler_entry(city, district):
            return {"skipped": True, "reason": "已有爬虫数据, llm不覆盖"}
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT id, source FROM price_distribution "
                "WHERE city=? AND district=?",
                (city, district),
            ).fetchone()
            if existing and existing["source"] == "crawler" and source == "crawler":
                # 爬虫重复抓取: 更新价格与时间戳
                conn.execute(
                    "UPDATE price_distribution SET "
                    "price_min=?, price_max=?, price_avg=?, note=?, "
                    "source_url=?, confidence=?, created_at=? WHERE id=?",
                    (price_min, price_max, price_avg, note,
                     source_url, confidence, now, existing["id"]),
                )
                row = conn.execute(
                    "SELECT * FROM price_distribution WHERE id=?",
                    (existing["id"],),
                ).fetchone()
                return self._row_to_dict(row)
            if existing and existing["source"] == "llm" and source == "crawler":
                # 爬虫数据覆盖llm旧数据
                conn.execute(
                    "UPDATE price_distribution SET "
                    "price_min=?, price_max=?, price_avg=?, note=?, "
                    "source=?, source_url=?, confidence=?, created_at=? "
                    "WHERE id=?",
                    (price_min, price_max, price_avg, note,
                     "crawler", source_url, confidence, now, existing["id"]),
                )
                row = conn.execute(
                    "SELECT * FROM price_distribution WHERE id=?",
                    (existing["id"],),
                ).fetchone()
                return self._row_to_dict(row)
            cur = conn.execute(
                "INSERT INTO price_distribution "
                "(city, district, price_min, price_max, price_avg, note, "
                "source, source_url, confidence, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (city, district, price_min, price_max, price_avg, note,
                 source, source_url, confidence, now),
            )
            row = conn.execute(
                "SELECT * FROM price_distribution WHERE id=?",
                (cur.lastrowid,),
            ).fetchone()
        return self._row_to_dict(row)

    def _has_crawler_entry(self, city: str, district: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM price_distribution "
                "WHERE city=? AND district=? AND source='crawler'",
                (city, district),
            ).fetchone()
        return row is not None

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        d["price_label"] = _format_price_label(row)
        return d

    def list(self, city: str = "") -> list:
        with self._connect() as conn:
            if city:
                rows = conn.execute(
                    "SELECT * FROM price_distribution WHERE city=? "
                    "ORDER BY district",
                    (city,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM price_distribution ORDER BY city, district"
                ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def get(self, city: str, district: str) -> dict:
        """精确取一条, 返回最可信的一条"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM price_distribution "
                "WHERE city=? AND district=? "
                "ORDER BY CASE source WHEN 'crawler' THEN 0 ELSE 1 END, "
                "confidence DESC LIMIT 1",
                (city, district),
            ).fetchone()
        return self._row_to_dict(row) if row else {}

    def stats(self) -> dict:
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) c FROM price_distribution"
            ).fetchone()["c"]
            by_source = conn.execute(
                "SELECT source, COUNT(*) c FROM price_distribution "
                "GROUP BY source"
            ).fetchall()
            by_city = conn.execute(
                "SELECT city, COUNT(*) c FROM price_distribution "
                "GROUP BY city"
            ).fetchall()
        return {
            "total": total,
            "by_source": {r["source"]: r["c"] for r in by_source},
            "by_city": {r["city"]: r["c"] for r in by_city},
        }

    def save_station_reference(self, city: str, station: str,
                               price_start: int,
                               source: str = "user_image",
                               note: str = "") -> dict:
        """保存地铁站起租参考价，与区域统计分开。"""
        if price_start < 300 or price_start > 100000:
            raise ValueError("站点起租价必须在 300-100000 元/月之间")
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO station_price_reference "
                "(city, station, price_start, source, note, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(city, station, source) DO UPDATE SET "
                "price_start=excluded.price_start, note=excluded.note, "
                "created_at=excluded.created_at",
                (city, station, price_start, source, note, now),
            )
            row = conn.execute(
                "SELECT * FROM station_price_reference "
                "WHERE city=? AND station=? AND source=?",
                (city, station, source),
            ).fetchone()
        return dict(row)

    def list_station_references(self, city: str = "") -> list:
        """查询地铁站起租参考价。"""
        with self._connect() as conn:
            if city:
                rows = conn.execute(
                    "SELECT * FROM station_price_reference "
                    "WHERE city=? ORDER BY price_start, station", (city,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM station_price_reference "
                    "ORDER BY city, price_start, station"
                ).fetchall()
        return [dict(row) for row in rows]


def _format_price_label(row) -> str:
    """把价格字段转成人类可读字符串, 如 3000-4500元/月"""
    lo = row["price_min"] or 0
    hi = row["price_max"] or row["price_avg"] or 0
    avg = row["price_avg"]
    if lo and hi and hi > lo:
        base = f"{lo}-{hi}"
    elif avg:
        base = str(avg)
    elif lo:
        base = f"{lo}+"
    elif hi:
        base = f"~{hi}"
    else:
        base = "未知"
    unit = row["unit"] or "元/月"
    return f"{base}{unit}"
