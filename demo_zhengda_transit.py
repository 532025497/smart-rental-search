# -*- coding: utf-8 -*-
"""正确版 — 正大中心 40分钟通勤可行域 (按真实地铁通勤时间, 非直线距离)

关键修正: 用 FeasibleDomain.calculate() 调用 direction/transit/integrated
对每个候选站算真实通勤时间, <=40min 才保留。这样能覆盖坐地铁多站的远端站点。
"""
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from config import GAODE_API_KEY, DATA_DIR
from src.gaode import GaodeClient
from src.feasible_domain import FeasibleDomain

city = "北京"
work = "正大中心"
commute = 40

print("=" * 70)
print(f"  正大中心 可行域 (真实通勤时间 <= {commute}min)")
print("=" * 70)

gaode = GaodeClient(GAODE_API_KEY)
fd = FeasibleDomain(gaode, DATA_DIR, max_concurrent=6)

def progress(cur, total, phase):
    if total and cur == total:
        print(f"  [{phase}] {cur}/{total} 完成")

t0 = time.time()
result = fd.calculate(city=city, work_address=work,
                      max_commute_min=commute,
                      progress_callback=progress)
elapsed = time.time() - t0

viable = result["viable_stations"]
print(f"\n  总站点: {result['total_stations']}")
print(f"  距离预筛后候选: {result['candidates_after_prefilter']}")
print(f"  通勤<= {commute}min 可行站: {result['viable_count']}")
print(f"  API调用: {result['api_calls']}次, 耗时{elapsed:.1f}s")

print(f"\n  {'站名':<12} {'通勤min':>7} {'换乘':>4} {'直线km':>7}")
print("  " + "-" * 40)
for st in viable:
    print(f"  {st['name']:<12} {st['commute_min']:>7} "
          f"{st['transfers']:>4} {st['distance_km']:>7}")

# 对每个可行站搜周边小区
print(f"\n[小区搜索] 每站半径1.2km, 最多6个")
all_xiaoqu = []
seen = set()
for st in viable:
    xqs = gaode.search_xiaoqu(st["lng"], st["lat"], radius=1200, max_count=6)
    for xq in xqs:
        if xq["name"] in seen:
            continue
        seen.add(xq["name"])
        all_xiaoqu.append({
            "name": xq["name"],
            "station": st["name"],
            "commute_min": st["commute_min"],
            "transfers": st["transfers"],
            "distance_to_metro": xq["distance"],
            "address": xq["address"],
        })
    time.sleep(0.3)

print(f"  共 {len(all_xiaoqu)} 个不重复小区")

ts = time.strftime("%Y%m%d_%H%M%S")
path = os.path.join(DATA_DIR, f"feasible_zhengda_{ts}.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump({
        "work": work,
        "work_location": result["work_location"],
        "commute_limit": commute,
        "requirements": ["独卫", "短租"],
        "viable_stations": viable,
        "xiaoqu": all_xiaoqu,
        "stats": {
            "total_stations": result["total_stations"],
            "viable_count": result["viable_count"],
            "api_calls": result["api_calls"],
        },
    }, f, ensure_ascii=False, indent=2)

print(f"\n  已保存: {path}")
