# -*- coding: utf-8 -*-
"""LLM兜底 — 生成三城各区大致房价 → 写入记忆库(爬虫缺失时补全)

用法:
    .venv/bin/python llm_price_seed.py            # 北京/上海/深圳
    .venv/bin/python llm_price_seed.py 上海        # 只跑上海

不覆盖已有爬虫数据 (PriceMemory内部保证)。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT
from src.llm import LLMClient
from src.price_memory import PriceMemory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DB = os.path.join(BASE_DIR, "data", "price_memory.db")

CITIES = ["北京", "上海", "深圳"]

PROMPT_TEMPLATE = """你是房地产市场数据助手。请提供{city}各行政区的房屋均价(元/㎡)，只输出JSON数组。

要求:
- 覆盖该市全部主要行政区
- 价格为元/㎡(每平米), 合理范围 10000-300000
- 提供 min/max(合理区间)和 avg(均价)三个数字
- 不要编造不存在的区
- 严格输出JSON, 格式: [{{"district":"xx区","min":10000,"max":20000,"avg":15000}}, ...]

请输出{city}各区房价:"""


def seed_city(city: str, store: PriceMemory, llm: LLMClient) -> int:
    if not LLM_API_KEY:
        print("[跳过] 未配置 LLM_API_KEY/DEEPSEEK_API_KEY，无法生成兜底数据")
        return 0
    print(f"\n===== LLM 生成: {city} =====")
    try:
        data = llm.chat_json(
            [{"role": "user", "content": PROMPT_TEMPLATE.format(city=city)}],
            temperature=0.2,
        )
    except Exception as e:
        print(f"  [llm] 请求失败: {e}")
        return 0

    if isinstance(data, dict):
        # 兼容 {"data": [...]} 包装
        for key in ("data", "list", "districts", "result"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        print(f"  [llm] 响应格式异常: {str(data)[:100]}")
        return 0

    saved = 0
    for item in data:
        district = str(item.get("district", "")).strip()
        if not district.endswith("区"):
            district += "区"
        try:
            lo = int(item.get("min") or item.get("avg") or 0)
            hi = int(item.get("max") or lo)
            avg = int(item.get("avg") or (lo + hi) // 2)
        except (TypeError, ValueError):
            continue
        if lo < 10000 or lo > 300000:
            continue
        row = store.save(
            city=city, district=district,
            price_min=lo, price_max=hi, price_avg=avg,
            note="LLM知识兜底",
            source="llm",
            confidence=0.45,
        )
        if not row.get("skipped"):
            saved += 1
    print(f"  [llm] {city} 写入 {saved} 条")
    return saved


def main() -> int:
    cities = sys.argv[1:] or CITIES
    store = PriceMemory(MEMORY_DB)
    llm = LLMClient(LLM_API_KEY, LLM_BASE_URL, LLM_MODEL,
                    timeout=LLM_TIMEOUT) if LLM_API_KEY else None
    total = 0
    for city in cities:
        total += seed_city(city, store, llm)
    print(f"\n总计写入 {total} 条. 记忆库: {MEMORY_DB}")
    print("当前记忆库统计:", store.stats())
    return 0


if __name__ == "__main__":
    sys.exit(main())
