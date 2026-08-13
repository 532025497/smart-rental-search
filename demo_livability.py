# -*- coding: utf-8 -*-
"""居住体验优选 — 对舒适通勤圈内可行站扫描周边生活配套并打分排序
口径:  feasible域内 commute<=30min 的站, 每站1次高德调用扫周边1km配套
       配套类型: 购物中心/超市/公园/医院/学校, 按丰富度加权打分
"""
import sys, os, json, glob, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from config import GAODE_API_KEY, DATA_DIR
from src.gaode import GaodeClient

src = sorted(glob.glob(os.path.join(DATA_DIR, "feasible_zhengda_*.json")))[-1]
data = json.load(open(src, encoding="utf-8"))
xq_by = {}
for xq in data["xiaoqu"]:
    xq_by.setdefault(xq["station"], []).append(xq)

# 候选: 舒适通勤圈 <=30min
cands = [s for s in data["viable_stations"] if s["commute_min"] <= 30]
cands.sort(key=lambda s: s["commute_min"])
print(f"候选站(<=30min): {[(s['name'], s['commute_min']) for s in cands]}\n")

g = GaodeClient(GAODE_API_KEY)
TYPES = "060101|060400|110101|090100|141200"  # 购物中心|超市|公园|医院|学校
CAT_NAME = {"06": "商业", "11": "公园", "09": "医疗", "14": "教育"}
WEIGHT = {"06": 3, "11": 4, "09": 2, "14": 2}   # 公园权重最高(最影响居住体验)

def scan(lng, lat):
    loc = f"{lng:.6f},{lat:.6f}"
    try:
        d = g._get("place/around", {"location": loc, "radius": 1000,
                                    "types": TYPES, "offset": 25,
                                    "page": 1, "extensions": "base"})
    except Exception as e:
        return {"count": 0, "cat": {}, "highlights": {}, "score": 0,
                "err": str(e)}
    count = int(d.get("count", 0))
    cat = {k: 0 for k in CAT_NAME}
    hl = {k: [] for k in CAT_NAME}
    for p in d.get("pois", []):
        tc = str(p.get("typecode", ""))[:2]
        if tc in cat:
            cat[tc] += 1
            if len(hl[tc]) < 3:
                hl[tc].append(p.get("name", ""))
    score = sum(cat[k] * WEIGHT[k] for k in cat) + math.log(count + 1) * 2
    return {"count": count, "cat": cat, "highlights": hl,
            "score": round(score, 1)}

results = []
for s in cands:
    sc = scan(s["lng"], s["lat"])
    xqs = sorted(xq_by.get(s["name"], []), key=lambda x: x["distance_to_metro"])
    results.append({
        "station": s["name"], "commute_min": s["commute_min"],
        "mode": s.get("mode", "transit"), "transfers": s["transfers"],
        "distance_km": s["distance_km"], "scan": sc,
        "xiaoqu": [x["name"] for x in xqs[:6]],
    })
    time.sleep(0.4)

results.sort(key=lambda r: -r["scan"]["score"])
print(f"高德调用次数: {g.call_count}\n")
print(f"{'排名':<4}{'站名':<10}{'通勤':>5}{'配套分':>7}{'总数':>6}  商业/公园/医疗/教育")
print("-" * 70)
for i, r in enumerate(results, 1):
    c = r["scan"]["cat"]
    print(f"{i:<4}{r['station']:<10}{r['commute_min']:>5}"
          f"{r['scan']['score']:>7}{r['scan']['count']:>6}  "
          f"{c.get('06',0)}/{c.get('11',0)}/{c.get('09',0)}/{c.get('14',0)}")

ts = time.strftime("%Y%m%d_%H%M%S")
path = os.path.join(DATA_DIR, f"livability_rank_{ts}.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n已保存: {path}")
