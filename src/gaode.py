# -*- coding: utf-8 -*-
"""高德地图API客户端 — 地理编码 / POI搜索 / 公交路径规划

仅使用Python标准库，无需安装第三方依赖。
"""
import json
import re
import time
import urllib.request
import urllib.parse
import urllib.error


class GaodeClient:
    """高德地图 Web服务API 客户端"""

    BASE_URL = "https://restapi.amap.com/v3"

    def __init__(self, api_key: str, timeout: int = 15):
        self.api_key = api_key
        self.timeout = timeout
        self._call_count = 0

    @property
    def call_count(self):
        """累计API调用次数"""
        return self._call_count

    # 高德免费Key常见限流错误码: 10003日配额超限 / 10004 QPS超限 / 其它偶发
    RETRYABLE_INFOCODES = {"10003", "10004", "10009", "10010", "10044", "20003"}

    def _get(self, path: str, params: dict, max_retries: int = 5) -> dict:
        """发送GET请求并解析JSON响应；对限流/网络错误自动退避重试"""
        params["key"] = self.api_key
        query = urllib.parse.urlencode(params)
        url = f"{self.BASE_URL}/{path}?{query}"
        last_err = "高德API请求失败(重试耗尽)"
        for attempt in range(max_retries):
            req = urllib.request.Request(url, headers={
                "User-Agent": "SmartRental/1.0"
            })
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                data = json.loads(raw.decode("utf-8"))
                self._call_count += 1
            except urllib.error.URLError as e:
                last_err = f"网络请求失败: {e}"
                time.sleep(0.5 * (attempt + 1))
                continue
            except json.JSONDecodeError:
                last_err = "API返回数据解析失败"
                time.sleep(0.5 * (attempt + 1))
                continue

            if data.get("status") == "1":
                return data

            err = data.get("info", "未知错误")
            errcode = str(data.get("infocode", ""))
            if errcode in self.RETRYABLE_INFOCODES and attempt < max_retries - 1:
                # 限流: 退避后重试
                time.sleep(0.6 * (attempt + 1))
                continue
            raise Exception(f"高德API错误({errcode}): {err}")
        raise Exception(last_err)

    # ----------------------------------------------------------------
    #  地理编码：地址 → 坐标
    # ----------------------------------------------------------------
    def geocode(self, address: str, city: str = None) -> tuple:
        """地址转坐标

        Args:
            address: 地址文本，如 "中关村软件园"
            city: 限制城市，如 "北京"

        Returns:
            (longitude, latitude) 浮点数元组
        """
        params = {"address": address}
        if city:
            params["city"] = city
        data = self._get("geocode/geo", params)
        geocodes = data.get("geocodes", [])
        if not geocodes:
            raise Exception(f"无法找到地址: {address}")
        location = geocodes[0]["location"]
        lng, lat = location.split(",")
        return float(lng), float(lat)

    # ----------------------------------------------------------------
    #  POI搜索：获取城市所有地铁站
    # ----------------------------------------------------------------
    @staticmethod
    def _clean_station_name(raw: str) -> str:
        """清理站名: 去掉'(地铁站)'/'（地铁站）'/'地铁站'及尾部空括号"""
        name = re.sub(r'[\(（]地铁站[\)）]', '', raw)
        name = name.replace("地铁站", "").strip()
        name = re.sub(r'[\(（]+[\)）]+\s*$', '', name).strip()
        return name

    def _poi_paginate(self, params: dict) -> list:
        """分页获取POI搜索结果"""
        all_pois = []
        page = 1
        while True:
            params = {**params, "page": page}
            try:
                data = self._get("place/text", params)
            except Exception:
                break
            pois = data.get("pois", [])
            if not pois:
                break
            all_pois.extend(pois)
            count = int(data.get("count", 0))
            if page * 25 >= count:
                break
            page += 1
        return all_pois

    def search_metro_stations(self, city: str) -> list:
        """搜索指定城市所有地铁站

        双策略搜索确保覆盖全面:
          策略1 — POI类型码150500(地铁站), 按类型检索不依赖名称
          策略2 — 关键词"地铁站", 补充策略1可能遗漏的站

        自动分页、去重、清理站名。

        Returns:
            [{"name": "西二旗", "lng": 116.305, "lat": 40.072, "address": "..."}]
        """
        # 策略1: 按POI类型码搜索
        pois_type = self._poi_paginate({
            "keywords": "",
            "types": "150500",
            "city": city,
            "city_limit": "true",
            "offset": 25,
            "extensions": "base",
        })

        # 策略2: 按关键词搜索 (补充)
        pois_kw = self._poi_paginate({
            "keywords": "地铁站",
            "city": city,
            "city_limit": "true",
            "offset": 25,
            "extensions": "base",
        })

        # 合并: 按站名去重
        seen = set()
        stations = []
        for poi in pois_type + pois_kw:
            clean_name = self._clean_station_name(poi.get("name", ""))
            if not clean_name or clean_name in seen:
                continue
            location = poi.get("location", "")
            if not location:
                continue
            try:
                lng, lat = location.split(",")
                lng, lat = float(lng), float(lat)
            except ValueError:
                continue
            seen.add(clean_name)
            stations.append({
                "name": clean_name,
                "lng": lng,
                "lat": lat,
                "address": poi.get("address", ""),
            })
        return stations

    # ----------------------------------------------------------------
    #  公交路径规划：算通勤时间
    # ----------------------------------------------------------------
    def transit_duration(self, origin: tuple, destination: tuple,
                         city: str) -> dict:
        """公交/地铁路径规划，取最短时间方案

        Args:
            origin: (lng, lat) 起点坐标
            destination: (lng, lat) 终点坐标
            city: 城市名

        Returns:
            {"duration_sec": 1980, "distance_m": 8500,
             "walking_m": 1200, "transfers": 1}
            无可达路径时返回 None
        """
        origin_str = f"{origin[0]:.6f},{origin[1]:.6f}"
        dest_str = f"{destination[0]:.6f},{destination[1]:.6f}"
        params = {
            "origin": origin_str,
            "destination": dest_str,
            "city": city,
            "cityd": city,
            "mode": 0,           # 最快捷模式
        }
        try:
            data = self._get("direction/transit/integrated", params)
        except Exception:
            return None

        route = data.get("route", {})
        transits = route.get("transits", [])
        if not transits:
            return None

        # 取最短时间方案
        best = min(transits, key=lambda t: int(t.get("duration", 999999)))
        duration = int(best.get("duration", 0))
        distance = int(best.get("distance", 0))
        walking = int(best.get("walking_distance", 0))

        # 统计换乘次数
        segments = best.get("segments", [])
        transit_segments = sum(
            1 for s in segments
            if s.get("segment", {}).get("type", "") in ("metro", "bus")
            or "metro" in s.get("segment", {}).get("type", "")
            or "bus" in s.get("segment", {}).get("type", "")
        )
        transfers = max(0, transit_segments - 1)

        return {
            "duration_sec": duration,
            "distance_m": distance,
            "walking_m": walking,
            "transfers": transfers,
        }

    # ----------------------------------------------------------------
    #  周边小区搜索：给定坐标 → 附近住宅小区
    # ----------------------------------------------------------------
    def search_xiaoqu(self, lng: float, lat: float,
                      radius: int = 2000,
                      max_count: int = 20) -> list:
        """搜索坐标周边住宅小区

        Args:
            lng, lat: 中心坐标
            radius: 搜索半径(米), 默认2km
            max_count: 最多返回数量

        Returns:
            [{"name": "融泽嘉园", "distance": 861, "address": "..."}]
        """
        location = f"{lng:.6f},{lat:.6f}"
        params = {
            "location": location,
            "radius": radius,
            "types": "120300",  # 住宅小区
            "offset": max_count,
            "page": 1,
            "extensions": "base",
        }
        try:
            data = self._get("place/around", params)
        except Exception:
            return []

        pois = data.get("pois", [])
        results = []
        for poi in pois[:max_count]:
            name = poi.get("name", "").strip()
            if not name:
                continue
            distance = int(poi.get("distance", 0))
            address = poi.get("address", "")
            results.append({
                "name": name,
                "distance": distance,
                "address": address,
            })

        # 按距离排序
        results.sort(key=lambda x: x["distance"])
        return results
