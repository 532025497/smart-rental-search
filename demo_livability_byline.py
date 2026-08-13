# -*- coding: utf-8 -*-
"""按线路整理居住体验 — 覆盖1号线/10号线/14号线沿线可行站
复用已扫描的9站, 仅补扫5个新站(四惠/建国门/团结湖/劲松/将台), 共5次调用
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

# 已有数据
fd_src = sorted(glob.glob(os.path.join(DATA_DIR, "feasible_zhengda_*.json")))[-1]
fd = json.load(open(fd_src, encoding="utf-8"))
st_meta = {s["name"]: s for s in fd["viable_stations"]}
xq_by = {}
for xq in fd["xiaoqu"]:
    xq_by.setdefault(xq["station"], []).append(xq)

liv_src = sorted(glob.glob(os.path.join(DATA_DIR, "livability_rank_*.json")))[-1]
liv = json.load(open(liv_src, encoding="utf-8"))
scanned = {r["station"]: r["scan"] for r in liv}

# 1/10/14号线沿线可行站 (含换乘站, 仅列这三条线归属)
LINE_MAP = {
    "国贸": ["1号线", "10号线"], "大望路": ["1号线", "14号线"],
    "永安里": ["1号线"], "四惠": ["1号线"], "建国门": ["1号线"],
    "呼家楼": ["10号线"], "十里河": ["10号线", "14号线"],
    "双井": ["10号线"], "宋家庄": ["10号线"], "团结湖": ["10号线"],
    "劲松": ["10号线"], "金台路": ["14号线"], "九龙山": ["14号线"],
    "将台": ["14号线"],
}

g = GaodeClient(GAODE_API_KEY)
TYPES = "060101|060400|110101|090100|141200"
CAT_NAME = {"06": "商业", "11": "公园", "09": "医疗", "14": "教育"}
WEIGHT = {"06": 3, "11": 4, "09": 2, "14": 2}

def scan(lng, lat):
    loc = f"{lng:.6f},{lat:.6f}"
    d = g._get("place/around", {"location": loc, "radius": 1000,
                                "types": TYPES, "offset": 25,
                                "page": 1, "extensions": "base"})
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
    return {"count": count, "cat": cat, "highlights": hl, "score": round(score, 1)}

# 组装14站, 缺的补扫
records = {}
for name in LINE_MAP:
    meta = st_meta[name]
    if name in scanned:
        sc = scanned[name]
    else:
        sc = scan(meta["lng"], meta["lat"])
        time.sleep(0.4)
    xqs = sorted(xq_by.get(name, []), key=lambda x: x["distance_to_metro"])
    records[name] = {
        "station": name, "lines": LINE_MAP[name],
        "commute_min": meta["commute_min"],
        "scan": sc, "xiaoqu": [x["name"] for x in xqs[:5]],
    }

print(f"新增调用: {g.call_count} 次 (复用{len(LINE_MAP)-g.call_count}站)\n")

# 按线路分组输出
for line in ["1号线", "10号线", "14号线"]:
    sts = [records[n] for n in LINE_MAP if line in LINE_MAP[n]]
    sts.sort(key=lambda r: r["commute_min"])
    print(f"===== {line}沿线 ({len(sts)}站) =====")
    for r in sts:
        c = r["scan"]["cat"]
        hl = r["scan"]["highlights"]
        park = "、".join(hl.get("11", [])) or "无公园"
        mall = "、".join(hl.get("06", [])) or "—"
        print(f"  {r['station']:<8} {r['commute_min']:>2}min "
              f"分{r['scan']['score']:>5} "
              f"[商{c.get('06',0)}/园{c.get('11',0)}/医{c.get('09',0)}/教{c.get('14',0)}] "
              f"公园:{park}")
        print(f"           小区: {'、'.join(r['xiaoqu'])}")
    print()

ts = time.strftime("%Y%m%d_%H%M%S")
path = os.path.join(DATA_DIR, f"livability_byline_{ts}.json")
with open(path, "w", encoding="utf-8") as f:
    json.dump(records, f, ensure_ascii=False, indent=2)
print(f"已保存: {path}")
