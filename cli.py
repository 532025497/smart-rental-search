# -*- coding: utf-8 -*-
"""智能租房搜索系统 — CLI入口

用法:
    python cli.py                     # 交互模式
    python cli.py --city 北京 --work "中关村软件园" --commute 40 --budget 3000-4500
"""
import sys
import os
import json
import time
import argparse

# 把项目根目录加入 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (GAODE_API_KEY, DEFAULT_CITY, DATA_DIR,
                    TRANSIT_SPEED_KMH, ROUTE_FACTOR, PREFILTER_MULTIPLIER,
                    MAX_CONCURRENT, REQUEST_TIMEOUT)
from src.gaode import GaodeClient
from src.feasible_domain import FeasibleDomain

# ----------------------------------------------------------------
#  进度显示
# ----------------------------------------------------------------
_PHASE_LABELS = {
    "geocode": "地理编码工作地点",
    "load_stations": "加载地铁站数据",
    "prefilter": "直线距离预筛选",
    "transit": "计算精确通勤时间",
}


def _progress(current, total, phase):
    label = _PHASE_LABELS.get(phase, phase)
    if phase == "transit" and total > 0:
        width = 30
        filled = int(width * current / total)
        bar = "#" * filled + "-" * (width - filled)
        pct = int(100 * current / total)
        print(f"\r  {label}: [{bar}] {current}/{total} ({pct}%)",
              end="", flush=True)
        if current >= total:
            print()
    else:
        if current >= total:
            print(f"  [OK] {label}")


# ----------------------------------------------------------------
#  结果展示
# ----------------------------------------------------------------
def _print_result(result):
    print()
    print("=" * 64)
    print(f"  可行域结果 (通勤 <= {result['max_commute_min']}分钟)")
    print("=" * 64)

    if not result["viable_stations"]:
        print("  未找到符合条件的站点")
        return

    # 表格
    print()
    hdr = (f"  {'站点':<14}{'通勤':>6}  {'直线距离':>8}  "
           f"{'换乘':>4}  {'步行':>6}  搜索关键词")
    print(hdr)
    print("  " + "-" * 58)

    for st in result["viable_stations"]:
        walk = f"{st['walking_m']}m" if st["walking_m"] < 1000 \
            else f"{st['walking_m']/1000:.1f}km"
        print(f"  {st['name']:<14}{st['commute_min']:>4}min  "
              f"{st['distance_km']:>6.1f}km  "
              f"{st['transfers']:>4}次  {walk:>6}  "
              f"{st['search_keywords']}")

    print("  " + "-" * 58)
    print(f"  共 {result['viable_count']} 个可行站点")

    print()
    print(f"  统计: 全城{result['total_stations']}站"
          f" -> 预筛后{result['candidates_after_prefilter']}站"
          f" -> 精确计算{result['viable_count']}站")
    print(f"  API调用: {result['api_calls']}次")

    b = result.get("budget", {})
    if b.get("min"):
        print(f"  预算: {b['min']}-{b['max']} 元/月 "
              f"(均价过滤将在采集阶段生效)")


def _save_result(result):
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(DATA_DIR, f"feasible_domain_{ts}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {path}")
    return path


# ----------------------------------------------------------------
#  主入口
# ----------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="智能租房搜索系统 - 可行域计算")
    parser.add_argument("--city", default=None, help="城市")
    parser.add_argument("--work", default=None, help="工作地点")
    parser.add_argument("--commute", type=int, default=None,
                        help="最大通勤时间(分钟)")
    parser.add_argument("--budget", default=None,
                        help="预算范围(如 3000-4500)")
    parser.add_argument("--refresh", action="store_true",
                        help="强制刷新地铁站缓存")
    args = parser.parse_args()

    print()
    print("=" * 64)
    print("  智能租房搜索系统 — 可行域计算")
    print("=" * 64)

    # 交互式输入
    city = args.city or input(
        f"\n  所在城市 [{DEFAULT_CITY}]: ").strip() or DEFAULT_CITY
    work = args.work or input(
        "  工作地点 (如: 中关村软件园): ").strip()
    if not work:
        print("  错误: 必须输入工作地点")
        return
    commute_raw = args.commute or input(
        "  最大通勤时间(分钟) [40]: ").strip()
    commute = int(commute_raw) if commute_raw else 40
    budget_raw = args.budget or input(
        "  预算范围(元/月, 如 3000-4500) [回车跳过]: ").strip()

    budget_min, budget_max = None, None
    if budget_raw:
        try:
            parts = budget_raw.replace(" ", "").split("-")
            budget_min = int(parts[0])
            budget_max = int(parts[1])
        except (ValueError, IndexError):
            print("  预算格式无效，跳过")

    # 确认
    print()
    print(f"  城市:     {city}")
    print(f"  工作地点: {work}")
    print(f"  通勤限制: {commute}分钟")
    if budget_min:
        print(f"  预算:     {budget_min}-{budget_max} 元/月")
    print()
    print("-" * 64)

    # 计算
    client = GaodeClient(GAODE_API_KEY, timeout=REQUEST_TIMEOUT)
    fd = FeasibleDomain(
        client, DATA_DIR,
        transit_speed=TRANSIT_SPEED_KMH,
        route_factor=ROUTE_FACTOR,
        prefilter_multiplier=PREFILTER_MULTIPLIER,
        max_concurrent=MAX_CONCURRENT,
    )

    # 刷新缓存
    if args.refresh:
        fd.metro_mgr.load_or_fetch(city, force_refresh=True)

    try:
        result = fd.calculate(
            city=city,
            work_address=work,
            max_commute_min=commute,
            budget_min=budget_min,
            budget_max=budget_max,
            progress_callback=_progress,
        )
    except Exception as e:
        print(f"\n  错误: {e}")
        return

    _print_result(result)
    _save_result(result)
    print()


if __name__ == "__main__":
    main()
