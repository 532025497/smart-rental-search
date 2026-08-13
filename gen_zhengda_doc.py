# -*- coding: utf-8 -*-
"""从 feasible_zhengda JSON 生成通勤小区整理文档 (按真实地铁通勤时间)"""
import sys, os, json, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from config import DATA_DIR, BASE_DIR

# 取最新的 feasible_zhengda JSON
files = sorted(glob.glob(os.path.join(DATA_DIR, "feasible_zhengda_*.json")))
src = files[-1]
data = json.load(open(src, encoding="utf-8"))

stations = data["viable_stations"]
xiaoqu = data["xiaoqu"]
work = data["work"]
limit = data["commute_limit"]
wloc = data["work_location"]

# 按站分组
by_station = {}
for xq in xiaoqu:
    by_station.setdefault(xq["station"], []).append(xq)
for st in stations:
    by_station.setdefault(st["name"], [])
    by_station[st["name"]].sort(key=lambda x: x["distance_to_metro"])

# 站点按通勤时间排序
stations_sorted = sorted(stations, key=lambda s: s["commute_min"])

def walk_min(m):
    return round(m / 1.3 / 60)

lines = []
lines.append(f"# {work} · {limit}分钟通勤圈 · 小区与通勤整理")
lines.append("")
lines.append(f"> 工作地坐标：{wloc['lng']:.6f}, {wloc['lat']:.6f} | "
             f"筛选口径：从各地铁站到工作地的**真实公交/地铁通勤时间 ≤ {limit} 分钟**"
             f"（高德 direction/transit 路径规划，含步行+候车+换乘）")
lines.append("")
lines.append(f"本次共算出 **{len(stations_sorted)} 个可达地铁站**、"
             f"**{len(xiaoqu)} 个周边小区**。特殊需求「独卫 / 短租」高德 API 无法提供，"
             f"需后续从豆瓣/小红书帖子中提取。")
lines.append("")

# 概览表
lines.append("## 一、可达地铁站概览（按通勤时间排序）")
lines.append("")
lines.append("| 站名 | 通勤(min) | 方式 | 换乘 | 直线距离 | 周边小区数 |")
lines.append("|------|:---:|:---:|:---:|:---:|:---:|")
for st in stations_sorted:
    mode = "步行" if st.get("mode") == "walking" else "地铁"
    n = len(by_station.get(st["name"], []))
    lines.append(f"| {st['name']} | {st['commute_min']} | {mode} | "
                 f"{st['transfers']} | {st['distance_km']}km | {n} |")
lines.append("")
lines.append("说明：通勤时间为高德路径规划返回的全程耗时（含两端步行与候车）。"
             "国贸、大望路因距工作地很近，高德只给步行方案，故标记为「步行」。")
lines.append("")

# 分站小区
lines.append("## 二、各站点周边小区")
lines.append("")
for st in stations_sorted:
    name = st["name"]
    xqs = by_station.get(name, [])
    mode = "步行直达" if st.get("mode") == "walking" else f"地铁{st['commute_min']}分钟"
    lines.append(f"### {name}站 · {mode} · 换乘{st['transfers']}次")
    lines.append("")
    if not xqs:
        lines.append("_（该站半径1.2km内未检索到小区）_")
        lines.append("")
        continue
    lines.append("| 小区 | 距地铁 | 步行约 | 地址 |")
    lines.append("|------|:---:|:---:|------|")
    for xq in xqs:
        wm = walk_min(xq["distance_to_metro"])
        addr = xq["address"].replace("|", "/") if xq["address"] else "—"
        lines.append(f"| {xq['name']} | {xq['distance_to_metro']}m | {wm}min | {addr} |")
    lines.append("")

# 限制说明
lines.append("## 三、数据边界与下一步")
lines.append("")
lines.append("| 维度 | 高德API能否提供 | 说明 |")
lines.append("|------|:---:|------|")
lines.append("| 可达站点 / 通勤时间 | ✅ | 本文档已覆盖 |")
lines.append("| 小区位置 / 距地铁距离 | ✅ | 本文档已覆盖 |")
lines.append("| 真实租金 | ❌ | 高德无租金数据，需爬虫采集挂牌价 |")
lines.append("| 独卫 / 短租 | ❌ | 仅存在于房源帖子文本中，需LLM提取 |")
lines.append("| 户型 / 面积 / 联系方式 | ❌ | 需爬虫 |")
lines.append("")
lines.append("建议下一步：以这 20 个站名 + 重点小区名作为关键词，"
             "驱动豆瓣/小红书采集，再由 LLM 提取「独卫/短租/租金」完成筛选闭环。")
lines.append("")

out = os.path.join(BASE_DIR, "..", "正大中心_通勤小区整理.md")
out = os.path.abspath(out)
with open(out, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"站点: {len(stations_sorted)}, 小区: {len(xiaoqu)}")
print(f"已生成: {out}")
