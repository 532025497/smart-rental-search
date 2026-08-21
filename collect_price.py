# -*- coding: utf-8 -*-
"""小红书浏览器搜索「城市 房价分布」→ 提取区域价格 → 写入记忆库

用法:
    .venv/bin/python collect_price.py                # 北京/上海/深圳
    .venv/bin/python collect_price.py 北京 上海      # 只跑指定城市

数据流:
    小红书搜索页(Playwright+登录态) → 相关性过滤 → 详情弹窗提取
    → 正则提取"区+价格范围" → PriceMemory入库(爬虫来源优先)
"""
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.collectors.xiaohongshu import XiaohongshuCollector
from src.price_memory import PriceMemory

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_DB = os.path.join(BASE_DIR, "data", "price_memory.db")

CITIES = ["北京", "上海", "深圳"]

# 每城使用的搜索关键词(越精准越好, 避免推荐流污染)
KEYWORDS = {
    "北京": ["北京 房价分布", "北京 各区房价 2024", "北京 房价地图"],
    "上海": ["上海 房价分布", "上海 各区房价 2024", "上海 房价地图"],
    "深圳": ["深圳 房价分布", "深圳 各区房价 2024", "深圳 房价地图"],
}

# 区名正则(中国主要城市的市辖区/区级)
DISTRICT_RE = re.compile(
    r"(东城|西城|朝阳|海淀|丰台|石景山|通州|昌平|大兴|顺义|房山|门头沟|"
    r"密云|怀柔|平谷|延庆|亦庄|望京|回龙观|天通苑|"
    r"黄浦|徐汇|长宁|静安|普陀|虹口|杨浦|闵行|宝山|嘉定|浦东|金山|松江|青浦|"
    r"奉贤|崇明|"
    r"福田|罗湖|南山|宝安|龙岗|盐田|光明|坪山|龙华)"
)

# 价格范围正则: 匹配 如 "3000-4500元" "3000~5000元/月" "均价4000元"
PRICE_RANGE_RE = re.compile(
    r"(\d{3,6})\s*[-~—至到]\s*(\d{3,6})\s*(?:元|块)?(?:/\s*[平月米])?"
)
PRICE_SINGLE_RE = re.compile(r"(?:均价|约|大概)?(\d{3,6})\s*(?:元|块)")


def score_post(post) -> float:
    """帖子可信度评分(0-100)。高分才允许入库。

    加分项:
        +20 标题含"房价/均价/价格表/分布图/地图"
        +15 内容含"元/㎡"或"每平" (单位价格, 专业表述)
        +15 内容含"同比/环比/涨幅" (数据感)
        +10 内容含具体年份(2023/2024/2025)
        +10 内容含3个及以上"xx区" (数据完整)
        +10 作者是认证号/媒体号标志(如"房产""数据""研究"等)
        +10 内容含"均价/中位数" (统计口径)
    减分项:
        -30 标题含"预测/会涨/跌"/"讨论/吧/吗/怎么样" (观点/问答帖)
        -20 内容明显是个人租房转让("转租/合租/求租/找室友")
        -15 内容长度<50字 (信息量不足)
    """
    title = post.title or ""
    content = post.content or ""
    text = f"{title}\n{content}"
    score = 0

    if re.search(r"房价|均价|价格表|分布图|房价地图", title):
        score += 20
    if re.search(r"元/㎡|元/平|每平", content):
        score += 15
    if re.search(r"同比|环比|涨幅|下跌|上涨", content):
        score += 15
    if re.search(r"202[3-6]|20[12]\d年", content):
        score += 10
    districts = set(re.findall(DISTRICT_RE, text))
    if len(districts) >= 3:
        score += 10
    if re.search(r"房产|数据|研究院|安居客|贝壳|链家|中指|克而瑞", text):
        score += 10
    if re.search(r"均价|中位数|统计", content):
        score += 10

    if re.search(r"预测|会涨|会跌|讨论|怎么样|是真是假", title):
        score -= 30
    if re.search(r"转租|合租|求租|找室友|押一付", text):
        score -= 20
    if len(content) < 50:
        score -= 15

    return score


def extract_price_map(text: str) -> dict:
    """从帖子文本中提取 {区名: (min, max, avg)}"""
    result = {}
    for m in re.finditer(r"([\u4e00-\u9fa5]{2,4}区|[A-Za-z]+)\s*[:：]?\s*"
                         r"(\d{3,6})\s*[-~—至到]\s*(\d{3,6})\s*(?:元|块)?",
                         text):
        district = m.group(1)
        lo, hi = int(m.group(2)), int(m.group(3))
        if DISTRICT_RE.search(district) and 1000 <= lo <= 200000:
            result[district] = (lo, hi, (lo + hi) // 2)
    return result


def parse_price_text(text: str) -> list:
    """宽松解析: 文本中出现的 区名+价格 组合 (覆盖月租与每平房价)"""
    entries = []
    for m in re.finditer(
            r"([\u4e00-\u9fa5]{2,4}区)\s*[:：]?(?:均价|约|大概|平均|参考价)?"
            r"\s*(\d{3,6})(?:\s*[-~—至到]\s*(\d{3,6}))?\s*(?:元|块)?",
            text):
        district = m.group(1)
        if not DISTRICT_RE.search(district):
            continue
        lo = int(m.group(2))
        hi = int(m.group(3)) if m.group(3) else None
        if lo < 1000 or lo > 300000:
            continue
        if hi and (hi < lo or hi > 300000):
            hi = None
        entries.append({
            "district": district,
            "min": lo,
            "max": hi,
            "avg": (lo + hi) // 2 if hi else lo,
        })
    return entries


def collect_city(city: str, store: PriceMemory, max_posts: int) -> int:
    saved = 0
    THRESHOLD = 55   # 可信度门槛: <55分不入库
    collector = XiaohongshuCollector(
        use_stub=False,
        max_posts=max_posts,
        state_path=os.path.join(BASE_DIR, "data", "xhs_state.json"),
        detail_delay=(6, 12),
        scroll_delay=(3, 5),
        search_suffix="",   # 房价分布关键词自带完整短语, 不加"租房"
    )
    for kw in KEYWORDS.get(city, []):
        print(f"\n===== 搜索: {kw} =====")
        posts = collector.collect(kw, city)
        for p in posts:
            text = f"{p.title}\n{p.content}"
            if not re.search(r"房价|均价|价格|租金|元/月|每平", text):
                continue
            score = score_post(p)
            if score < THRESHOLD:
                print(f"  [过滤] 可信度{score:.0f} < {THRESHOLD}: "
                      f"{p.title[:30]} (非高可信帖子)")
                continue
            entries = parse_price_text(text)
            if not entries:
                print(f"  [过滤] 无有效价格数据: {p.title[:30]}")
                continue
            print(f"  [通过] 可信度{score:.0f} | {p.title[:30]} "
                  f"→ {len(entries)}个区")
            for e in entries:
                row = store.save(
                    city=city,
                    district=e["district"],
                    price_min=e["min"],
                    price_max=e["max"],
                    price_avg=e["avg"],
                    note=p.title[:80],
                    source="crawler",
                    source_url=p.url,
                    confidence=min(0.95, 0.5 + score / 200),  # 高分→高置信
                )
                if not row.get("skipped"):
                    saved += 1
        time.sleep(random_sleep())
    return saved


def random_sleep():
    import random
    return random.uniform(20, 45)


def main() -> int:
    cities = sys.argv[1:] or CITIES
    store = PriceMemory(MEMORY_DB)
    total = 0
    for city in cities:
        if city not in CITIES:
            print(f"[跳过] 未知城市: {city}, 支持 {CITIES}")
            continue
        n = collect_city(city, store, max_posts=6)
        print(f"[{city}] 完成, 本次写入 {n} 条")
        total += n
    print(f"\n总计写入 {total} 条. 记忆库: {MEMORY_DB}")
    print("当前记忆库统计:", store.stats())
    return 0


if __name__ == "__main__":
    sys.exit(main())
