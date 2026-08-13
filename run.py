# -*- coding: utf-8 -*-
"""智能租房搜索系统 — 主运行脚本

串联全流程: 规划师→开发→评判器 三方协作Loop

用法:
    python run.py
    python run.py --city 北京 --work "中关村软件园" --commute 40 --budget 3000-4500
    python run.py --no-llm          # 跳过LLM提取，只看规划和采集
"""
import sys
import os
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from config import (
    GAODE_API_KEY, DEFAULT_CITY, DATA_DIR,
    TRANSIT_SPEED_KMH, ROUTE_FACTOR, PREFILTER_MULTIPLIER,
    MAX_CONCURRENT, REQUEST_TIMEOUT,
    LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, LLM_TIMEOUT,
    MAX_EXTRACTION_RETRIES,
)
from src.gaode import GaodeClient
from src.llm import LLMClient
from src.feasible_domain import FeasibleDomain
from src.agents.planner import PlannerAgent
from src.agents.developer import DeveloperAgent
from src.agents.evaluator import EvaluatorAgent
from src.loop import RentalSearchLoop
from src.collectors.douban import DoubanCollector
from src.models import UserRequirement, Platform


def progress_bar(current, total, phase):
    labels = {
        "geocode": "地理编码",
        "load_stations": "加载地铁站",
        "prefilter": "直线距离预筛选",
        "transit": "精确通勤计算",
    }
    label = labels.get(phase, phase)
    if phase == "transit" and total > 0:
        w = 30
        filled = int(w * current / total)
        bar = "#" * filled + "-" * (w - filled)
        pct = int(100 * current / total)
        print(f"\r  {label}: [{bar}] {current}/{total} ({pct}%)",
              end="", flush=True)
        if current >= total:
            print()
    else:
        if current >= total:
            print(f"  [OK] {label}")


def print_listings(listings):
    """展示提取的房源"""
    if not listings:
        print("\n  无有效房源")
        return

    print(f"\n{'='*64}")
    print(f"  提取到的房源 ({len(listings)}条)")
    print(f"{'='*64}")

    for i, li in enumerate(listings):
        print(f"\n  [{i+1}] {li.title}")
        print(f"      价格: {li.price_monthly or '?'}元/月 "
              f"({li.deposit_method or '?'})")
        print(f"      位置: {li.district} {li.neighborhood} "
              f"({li.address_raw or '?'})")
        print(f"      户型: {li.room_type} {li.layout} "
              f"{li.area_sqm or '?'}平  {li.floor or ''}")
        print(f"      入住: {li.available_from or '?'}")
        print(f"      联系: {li.contact or '?'}")
        if li.highlights:
            print(f"      亮点: {li.highlights}")
        print(f"      来源: {li.source_platform} "
              f"提取{li.extraction_attempts}轮 "
              f"置信度={li.confidence:.2f}")


def main():
    parser = argparse.ArgumentParser(
        description="智能租房搜索系统 — 多Agent协作Loop")
    parser.add_argument("--city", default=None)
    parser.add_argument("--work", default=None, help="工作地点")
    parser.add_argument("--commute", type=int, default=None, help="通勤时间(分钟)")
    parser.add_argument("--budget", default=None, help="预算(如3000-4500)")
    parser.add_argument("--no-llm", action="store_true",
                        help="跳过LLM提取")
    parser.add_argument("--refresh", action="store_true",
                        help="刷新地铁站缓存")
    args = parser.parse_args()

    print()
    print("=" * 64)
    print("  智能租房搜索系统 — 多Agent协作Loop")
    print("  规划师 → 开发 → 评判器 → (反馈) → 循环")
    print("=" * 64)

    # ---- 用户输入 ----
    city = args.city or input(
        f"\n  城市 [{DEFAULT_CITY}]: ").strip() or DEFAULT_CITY
    work = args.work or input(
        "  工作地点 (如: 中关村软件园): ").strip()
    if not work:
        print("  错误: 必须输入工作地点")
        return
    commute_raw = args.commute or input(
        "  最大通勤时间(分钟) [40]: ").strip()
    commute = int(commute_raw) if commute_raw else 40
    budget_raw = args.budget or input(
        "  预算(元/月, 如3000-4500) [回车跳过]: ").strip()

    budget_min, budget_max = None, None
    if budget_raw:
        try:
            parts = budget_raw.replace(" ", "").split("-")
            budget_min = int(parts[0])
            budget_max = int(parts[1])
        except (ValueError, IndexError):
            print("  预算格式无效，跳过")

    # ---- LLM检查 ----
    use_llm = not args.no_llm and bool(LLM_API_KEY)
    if not use_llm and not args.no_llm:
        print("\n  [注意] 未配置LLM API Key")
        print("  设置环境变量 LLM_API_KEY 或在 config.py 中填入")
        print("  推荐: DeepSeek (https://platform.deepseek.com/)")
        print("  本次将跳过LLM提取，只运行规划和采集\n")
        use_llm = False

    # ---- 确认 ----
    print(f"\n  城市:     {city}")
    print(f"  工作地点: {work}")
    print(f"  通勤限制: {commute}分钟")
    if budget_min:
        print(f"  预算:     {budget_min}-{budget_max} 元/月")
    print(f"  LLM提取:  {'启用' if use_llm else '跳过'}")
    print()

    # ---- 初始化组件 ----
    gaode = GaodeClient(GAODE_API_KEY, timeout=REQUEST_TIMEOUT)
    fd = FeasibleDomain(
        gaode, DATA_DIR,
        transit_speed=TRANSIT_SPEED_KMH,
        route_factor=ROUTE_FACTOR,
        prefilter_multiplier=PREFILTER_MULTIPLIER,
        max_concurrent=MAX_CONCURRENT,
    )

    if args.refresh:
        fd.metro_mgr.load_or_fetch(city, force_refresh=True)

    # LLM客户端
    llm = None
    if use_llm:
        llm = LLMClient(
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
            timeout=LLM_TIMEOUT,
        )

    # 采集器
    douban = DoubanCollector(use_stub=True)  # MVP: 示例数据

    # 三个Agent
    planner = PlannerAgent(fd)
    developer = DeveloperAgent(llm)
    developer.register_collector(Platform.DOUBAN, douban)
    evaluator = EvaluatorAgent()

    # Loop协调器
    loop = RentalSearchLoop(planner, developer, evaluator,
                            max_retries=MAX_EXTRACTION_RETRIES)

    # ---- 运行 ----
    requirement = UserRequirement(
        city=city,
        work_address=work,
        max_commute_min=commute,
        budget_min=budget_min,
        budget_max=budget_max,
    )

    start_time = time.time()

    try:
        result = loop.run(requirement, progress_callback=progress_bar)
    except Exception as e:
        print(f"\n  系统错误: {e}")
        import traceback
        traceback.print_exc()
        return

    elapsed = time.time() - start_time

    # ---- 展示结果 ----
    if use_llm and result.get("listings"):
        print_listings(result["listings"])

    # ---- 保存 ----
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(DATA_DIR, f"search_result_{ts}.json")

    # Listing转dict
    listings_data = []
    for li in result.get("listings", []):
        listings_data.append({
            "title": li.title,
            "price_monthly": li.price_monthly,
            "deposit_method": li.deposit_method,
            "city": li.city,
            "district": li.district,
            "neighborhood": li.neighborhood,
            "address_raw": li.address_raw,
            "room_type": li.room_type,
            "layout": li.layout,
            "area_sqm": li.area_sqm,
            "floor": li.floor,
            "contact": li.contact,
            "available_from": li.available_from,
            "highlights": li.highlights,
            "source_platform": li.source_platform,
            "confidence": li.confidence,
            "extraction_attempts": li.extraction_attempts,
        })

    output = {
        "requirement": {
            "city": city, "work_address": work,
            "max_commute_min": commute,
            "budget": {"min": budget_min, "max": budget_max},
        },
        "feasible_stations": result.get("plan", {}).get("viable_stations", []),
        "listings": listings_data,
        "stats": result.get("stats", {}),
        "elapsed_sec": round(elapsed, 1),
        "timestamp": ts,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n  耗时: {elapsed:.1f}秒")
    print(f"  结果已保存: {out_path}")
    print()


if __name__ == "__main__":
    main()
