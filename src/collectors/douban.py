# -*- coding: utf-8 -*-
"""豆瓣租房信息采集器 — 真实实现 + stub模式

采集流程:
  1. 浏览指定豆瓣租房小组的讨论列表
  2. 按关键词过滤帖子标题
  3. 逐个访问帖子详情页，提取正文+评论
  4. 随机延迟3-8秒防反爬

已验证可访问的小组:
  - 279962: 北京租房(非中介)  https://www.douban.com/group/279962/
"""
import time
import random
import re
import requests
from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector
from src.models import RawPost


class DoubanCollector(BaseCollector):
    """豆瓣租房信息采集器"""

    platform_name = "douban"

    GROUPS_BY_CITY = {
        "北京": [
            ("279962", "北京租房(非中介)"),
        ],
        "上海": [],
    }

    DEFAULT_HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": ("text/html,application/xhtml+xml,application/xml;"
                   "q=0.9,*/*;q=0.8"),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    def __init__(self, use_stub: bool = True,
                 delay_range: tuple = (3, 8),
                 max_pages: int = 2,
                 max_posts: int = 20):
        self.use_stub = use_stub
        self.delay_range = delay_range
        self.max_pages = max_pages
        self.max_posts = max_posts
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)

    def collect(self, keyword: str, city: str) -> list[RawPost]:
        if self.use_stub:
            return self._stub_collect(keyword, city)
        return self._real_collect(keyword, city)

    # ----------------------------------------------------------------
    #  真实爬取
    # ----------------------------------------------------------------
    def _real_collect(self, keyword: str, city: str) -> list[RawPost]:
        groups = self.GROUPS_BY_CITY.get(city, [])
        if not groups:
            print(f"  [douban] 未配置 {city} 的租房小组")
            return []

        search_term = keyword.split()[0] if " " in keyword else keyword

        all_posts = []
        for group_id, group_name in groups:
            print(f"  [douban] 浏览: {group_name} ({group_id})")
            post_links = self._browse_group(group_id, search_term)
            print(f"  [douban] 匹配 {len(post_links)} 条")

            for url, title in post_links[:self.max_posts]:
                if len(all_posts) >= self.max_posts:
                    break
                time.sleep(random.uniform(*self.delay_range))
                post = self._fetch_post_detail(url, title)
                if post:
                    all_posts.append(post)
            if len(all_posts) >= self.max_posts:
                break

        return all_posts

    def _browse_group(self, group_id: str,
                      search_term: str = "") -> list[tuple]:
        """浏览小组讨论列表，返回所有帖子(url, title)

        采集阶段做"轻过滤": 仅按标题包含search_term做筛选。
        - 仍保留"广撒网下游过滤"原则: 评判器后续做地址/价格/字段硬验证
        - 但避免对显然不相干(如搜索西二旗却抓常营帖)的帖子浪费LLM预算
        - 若标题过滤后0条, fallback到无过滤(避免空结果)
        """
        all_results = []
        matched_results = []

        for page in range(self.max_pages):
            start = page * 25
            url = f"https://www.douban.com/group/{group_id}/discussion"
            params = {"start": start}

            try:
                resp = self.session.get(url, params=params, timeout=15)
            except Exception as e:
                print(f"  [douban] 列表获取失败(page={page}): {e}")
                break

            if resp.status_code != 200:
                if page == 0:
                    # 第一页非200通常是IP被ban/需登录，需可见提示
                    print(f"  [douban] 列表页HTTP {resp.status_code} "
                          f"(可能IP被限制或需登录cookie)")
                break

            soup = BeautifulSoup(resp.text, "html.parser")
            for tr in soup.select("table.olt tr"):
                a = tr.select_one("td.title a") or tr.select_one("a")
                if not a:
                    continue
                href = a.get("href", "")
                title = a.get("title", "") or a.get_text(strip=True)
                if "/group/topic/" not in href or not title:
                    continue
                # 跳过求租帖(求租≠出租)
                if "求租" in title or "求房源" in title:
                    continue
                all_results.append((href, title))
                # 标题含search_term则纳入"匹配"集合
                if search_term and search_term in title:
                    matched_results.append((href, title))

            if page < self.max_pages - 1:
                time.sleep(random.uniform(*self.delay_range))

        # fallback: 若有search_term但0匹配, 用全部结果(广撒网兜底)
        if search_term and not matched_results:
            print(f"  [douban] 标题含'{search_term}'的帖子0条, "
                  f"fallback到全量(共{len(all_results)}条)")
            return all_results
        return matched_results if search_term else all_results

    def _fetch_post_detail(self, url: str, title: str):
        """获取帖子详情，提取正文+评论"""
        try:
            resp = self.session.get(url, timeout=15)
        except Exception as e:
            print(f"  [douban] 详情失败: {e}")
            return None

        if resp.status_code != 200:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")

        # 正文
        content = ""
        cdiv = (soup.select_one("div.topic-content")
                or soup.select_one("article"))
        if cdiv:
            for br in cdiv.find_all("br"):
                br.replace_with("\n")
            content = cdiv.get_text(strip=True)

        # 评论
        comments = []
        for item in soup.select("div.comment-item"):
            p = item.select_one("p.comment-content") or item.select_one("p")
            if p:
                comments.append(p.get_text(strip=True))
        comments_text = "\n".join(comments) if comments else ""

        # 作者
        author = ""
        ael = soup.select_one("span.from a") or soup.select_one("a.user-info")
        if ael:
            author = ael.get_text(strip=True)

        # 发布时间
        published = ""
        tel = (soup.select_one("span.create-time")
               or soup.select_one("span.color-green"))
        if tel:
            published = tel.get_text(strip=True)

        # 帖子ID
        post_id = ""
        m = re.search(r"/topic/(\d+)", url)
        if m:
            post_id = m.group(1)

        return RawPost(
            platform="douban", post_id=post_id, url=url,
            title=title, content=content, comments=comments_text,
            author=author, published_at=published, collected_at=ts,
        )

    # ----------------------------------------------------------------
    #  示例数据 (测试Loop用)
    # ----------------------------------------------------------------
    def _stub_collect(self, keyword: str, city: str) -> list[RawPost]:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        samples = [
            RawPost(
                platform="douban", post_id="stub_001",
                url="https://www.douban.com/group/topic/stub001/",
                title="【西二旗】转租一居室 2500/月 近地铁",
                content=("因工作变动转租西二旗地铁站附近一居室。\n"
                         "位置: 海淀区西二旗地铁站B口步行5分钟\n"
                         "租金: 2500元/月，押一付三\n"
                         "面积: 约15平\n楼层: 6/18层，有电梯\n"
                         "入住时间: 随时可入住\n联系方式: 微信 xxx123\n"
                         "亮点: 近地铁，精装修，可短租"),
                comments="回复1: 还在吗？\n回复2: 在的",
                author="用户A", published_at="2026-07-15", collected_at=ts,
            ),
            RawPost(
                platform="douban", post_id="stub_002",
                url="https://www.douban.com/group/topic/stub002/",
                title="西二旗附近合租找室友",
                content=("西二旗地铁站附近两居室找一个室友。\n"
                         "小区就在地铁旁边，走路3分钟。\n"
                         "次卧，大概10平左右。押一付一。\n"
                         "有意的豆邮联系。"),
                comments="回复1: 多少钱一个月？",
                author="用户B", published_at="2026-07-14", collected_at=ts,
            ),
            RawPost(
                platform="douban", post_id="stub_003",
                url="https://www.douban.com/group/topic/stub003/",
                title="求租西二旗附近一居室",
                content=("本人女，想在西二旗附近租一个一居室。\n"
                         "预算3000以内，最好是精装修。有的请留言。"),
                comments="",
                author="用户C", published_at="2026-07-15", collected_at=ts,
            ),
            RawPost(
                platform="douban", post_id="stub_004",
                url="https://www.douban.com/group/topic/stub004/",
                title="朱辛庄转租两居室 4000/月",
                content=("昌平区朱辛庄地铁站旁边两居室转租。\n"
                         "租金: 4000元/月，押一付三\n面积: 65平\n"
                         "户型: 2室1厅1卫\n楼层: 中层/12层\n"
                         "朝向: 南北通透\n装修: 精装\n"
                         "入住: 8月初可入住\n联系: 微信 zhu123456\n"
                         "亮点: 近地铁8号线/昌平线，有电梯，可养宠物"),
                comments="回复1: 押一付三太贵了\n回复2: 可以商量",
                author="用户D", published_at="2026-07-13", collected_at=ts,
            ),
        ]
        kw = keyword.lower()
        matched = [p for p in samples
                   if kw in p.title.lower() or kw in p.content.lower()]
        return matched or samples
