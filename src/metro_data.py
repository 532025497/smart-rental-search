# -*- coding: utf-8 -*-
"""地铁站数据管理 — 从高德获取并缓存到本地JSON"""
import json
import os
import time
from src.gaode import GaodeClient


class MetroDataManager:
    """地铁站数据的获取与本地缓存"""

    def __init__(self, gaode: GaodeClient, data_dir: str):
        self.gaode = gaode
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def _cache_path(self, city: str) -> str:
        safe = city.replace("/", "_").replace("\\", "_")
        return os.path.join(self.data_dir, f"metro_stations_{safe}.json")

    def load_or_fetch(self, city: str, force_refresh: bool = False) -> list:
        """加载地铁站数据，优先使用本地缓存

        Args:
            city: 城市名
            force_refresh: 强制刷新缓存

        Returns:
            [{"name", "lng", "lat", "address"}, ...]
        """
        cache_path = self._cache_path(city)

        if not force_refresh and os.path.exists(cache_path):
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            if cache.get("stations"):
                return cache["stations"]

        # 从高德API获取
        stations = self.gaode.search_metro_stations(city)

        cache = {
            "city": city,
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "count": len(stations),
            "stations": stations,
        }
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)

        return stations
