# -*- coding: utf-8 -*-
"""可行域计算器 — 基于工作地点+通勤时间+预算，计算可行居住区域

核心流程：
  1. 地理编码工作地点
  2. 加载城市地铁站数据（缓存）
  3. 直线距离预筛选（省API调用）
  4. 并发精确通勤时间计算
  5. 过滤+排序+输出
"""
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.gaode import GaodeClient
from src.metro_data import MetroDataManager


class FeasibleDomain:
    """可行域计算器"""

    def __init__(self, gaode: GaodeClient, data_dir: str,
                 transit_speed: float = 22.0,
                 route_factor: float = 1.3,
                 prefilter_multiplier: float = 1.5,
                 max_concurrent: int = 10):
        self.gaode = gaode
        self.metro_mgr = MetroDataManager(gaode, data_dir)
        self.transit_speed = transit_speed      # km/h
        self.route_factor = route_factor        # 实际路线/直线距离
        self.prefilter_multiplier = prefilter_multiplier
        self.max_concurrent = max_concurrent

    @staticmethod
    def haversine_km(lng1: float, lat1: float,
                     lng2: float, lat2: float) -> float:
        """Haversine公式计算两点直线距离(km)"""
        R = 6371.0
        lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
        dlat = lat2 - lat1
        dlng = lng2 - lng1
        a = (math.sin(dlat / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2)
        return R * 2 * math.asin(math.sqrt(a))

    def _estimate_rough_time(self, distance_km: float) -> float:
        """估算粗略通勤时间(分钟)"""
        actual_dist = distance_km * self.route_factor
        return actual_dist / self.transit_speed * 60

    def _check_station(self, st: dict, work_lng: float, work_lat: float,
                       city: str, max_commute_min: int) -> dict:
        """检查单个站点的通勤时间（供线程池调用）"""
        result = self.gaode.transit_duration(
            (st["lng"], st["lat"]),
            (work_lng, work_lat),
            city
        )
        if result is None:
            # 近距离站点高德只返回步行方案(无transit)，用步行时间兜底
            # 步行速度约1.3m/s ≈ 0.078km/min
            walk_min = st["_distance_km"] / 0.078
            if walk_min <= max_commute_min:
                return {
                    "name": st["name"],
                    "lng": st["lng"],
                    "lat": st["lat"],
                    "commute_min": round(walk_min),
                    "distance_km": st["_distance_km"],
                    "walking_m": int(st["_distance_km"] * 1000),
                    "transfers": 0,
                    "mode": "walking",
                    "search_keywords": f"{st['name']} 租房",
                }
            return None
        commute_min = result["duration_sec"] / 60
        if commute_min <= max_commute_min:
            return {
                "name": st["name"],
                "lng": st["lng"],
                "lat": st["lat"],
                "commute_min": round(commute_min),
                "distance_km": st["_distance_km"],
                "walking_m": result["walking_m"],
                "transfers": result["transfers"],
                "mode": "transit",
                "search_keywords": f"{st['name']} 租房",
            }
        return None

    def calculate(self, city: str, work_address: str,
                  max_commute_min: int,
                  budget_min: int = None, budget_max: int = None,
                  progress_callback=None) -> dict:
        """计算可行域

        Args:
            city: 城市名
            work_address: 工作地点文本
            max_commute_min: 最大通勤时间(分钟)
            budget_min: 预算下限(元/月)
            budget_max: 预算上限(元/月)
            progress_callback: 回调 fn(current, total, phase)

        Returns:
            dict: 可行域完整结果
        """
        # ---- Step 1: 地理编码 ----
        if progress_callback:
            progress_callback(0, 1, "geocode")
        work_lng, work_lat = self.gaode.geocode(work_address, city)
        if progress_callback:
            progress_callback(1, 1, "geocode")

        # ---- Step 2: 加载地铁站 ----
        if progress_callback:
            progress_callback(0, 1, "load_stations")
        stations = self.metro_mgr.load_or_fetch(city)
        if progress_callback:
            progress_callback(1, 1, "load_stations")

        total_stations = len(stations)

        # ---- Step 3: 直线距离预筛选 ----
        if progress_callback:
            progress_callback(0, 1, "prefilter")
        candidates = []
        skip_count = 0
        for st in stations:
            dist = self.haversine_km(work_lng, work_lat, st["lng"], st["lat"])
            rough_time = self._estimate_rough_time(dist)
            if rough_time > max_commute_min * self.prefilter_multiplier:
                skip_count += 1
                continue
            st["_distance_km"] = round(dist, 2)
            st["_rough_time_min"] = round(rough_time, 1)
            candidates.append(st)
        if progress_callback:
            progress_callback(1, 1, "prefilter")

        # ---- Step 4: 并发精确通勤计算 ----
        viable = []
        total = len(candidates)

        if total == 0:
            if progress_callback:
                progress_callback(0, 0, "transit")
        else:
            with ThreadPoolExecutor(max_workers=self.max_concurrent) as pool:
                futures = {
                    pool.submit(self._check_station, st,
                                work_lng, work_lat, city, max_commute_min): idx
                    for idx, st in enumerate(candidates)
                }
                done = 0
                for future in as_completed(futures):
                    done += 1
                    if progress_callback:
                        progress_callback(done, total, "transit")
                    res = future.result()
                    if res:
                        viable.append(res)

        # ---- Step 5: 排序 ----
        viable.sort(key=lambda x: x["commute_min"])

        return {
            "city": city,
            "work_address": work_address,
            "work_location": {"lng": work_lng, "lat": work_lat},
            "max_commute_min": max_commute_min,
            "budget": {"min": budget_min, "max": budget_max},
            "total_stations": total_stations,
            "filtered_by_distance": skip_count,
            "candidates_after_prefilter": len(candidates),
            "viable_count": len(viable),
            "viable_stations": viable,
            "calculated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "api_calls": self.gaode.call_count,
        }
