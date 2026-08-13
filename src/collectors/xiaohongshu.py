# -*- coding: utf-8 -*-
"""小红书租房信息采集器 — stub + 真实模式

小红书反爬严格，真实模式需要cookie。
当前实现:
  - stub模式: 返回模拟数据，用于测试Loop流程
  - 真实模式: 尝试用requests爬取（大概率被拦，需要cookie）

后续改进:
  - 接入第三方API（如MediaCrawler）
  - 用户提供cookie后模拟登录态
"""
import time
import random
import requests
from src.collectors.base import BaseCollector
from src.models import RawPost


class XiaohongshuCollector(BaseCollector):
    """小红书租房信息采集器"""

    platform_name = "xiaohongshu"

    DEFAULT_HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://www.xiaohongshu.com",
        "Referer": "https://www.xiaohongshu.com/",
    }

    def __init__(self, use_stub: bool = True,
                 cookie: str = "",
                 max_posts: int = 10):
        self.use_stub = use_stub
        self.cookie = cookie
        self.max_posts = max_posts
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)
        if cookie:
            self.session.headers["Cookie"] = cookie

    def collect(self, keyword: str, city: str) -> list[RawPost]:
        if self.use_stub:
            return self._stub_collect(keyword, city)
        return self._real_collect(keyword, city)

    # ----------------------------------------------------------------
    #  Stub模式
    # ----------------------------------------------------------------
    def _stub_collect(self, keyword: str, city: str) -> list[RawPost]:
        """返回模拟的小红书租房帖"""
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        posts = [
            RawPost(
                platform="xiaohongshu",
                post_id="xhs_stub_001",
                url="https://www.xiaohongshu.com/explore/stub001",
                title=f"【{city}租房】西二旗附近精装主卧 近地铁 采光好",
                content=("西二旗地铁站步行8分钟，小区环境好，物业管理严格。\n"
                        "主卧朝南，带独立卫生间，家具家电齐全。\n"
                        "月租2800，押一付三，无中介费。\n"
                        "随时可看房，联系方式：微信 xhs_rent_001"),
                comments="想看房！\n已私信",
                author="小红书租房达人",
                published_at=ts,
                collected_at=ts,
            ),
            RawPost(
                platform="xiaohongshu",
                post_id="xhs_stub_002",
                url="https://www.xiaohongshu.com/explore/stub002",
                title=f"【转租】回龙观地铁口 两居室合租 女生优先",
                content=("回龙观地铁站3分钟，小区绿化好，周边配套齐全。\n"
                        "两居室合租，主卧已出租，次卧找女生室友。\n"
                        "月租2200，押一付一，可短租。\n"
                        "要求：爱干净，不养宠物。联系：微信 xhs_rent_002"),
                comments="还在吗？\n价格可以商量",
                author="转租小能手",
                published_at=ts,
                collected_at=ts,
            ),
            RawPost(
                platform="xiaohongshu",
                post_id="xhs_stub_003",
                url="https://www.xiaohongshu.com/explore/stub003",
                title=f"【房东直租】龙泽苑 整租一居室 精装修",
                content=("龙泽地铁站5分钟，小区新装修，环境优雅。\n"
                        "整租一居室，50平，南北通透，采光极佳。\n"
                        "月租3500，押一付三，长租优惠。\n"
                        "房东直租，无中介费。联系：电话 13800138000"),
                comments="房子还在吗？\n可以养猫吗？",
                author="房东阿姨",
                published_at=ts,
                collected_at=ts,
            ),
            RawPost(
                platform="xiaohongshu",
                post_id="xhs_stub_004",
                url="https://www.xiaohongshu.com/explore/stub004",
                title="【求租】西二旗附近求一居室 预算3000以内",
                content=("求租西二旗附近一居室，预算3000以内。\n"
                        "要求：干净卫生，有独立卫生间，近地铁。\n"
                        "有意请私信，谢谢！"),
                comments="",
                author="求租小可爱",
                published_at=ts,
                collected_at=ts,
            ),
        ]
        return posts[:self.max_posts]

    # ----------------------------------------------------------------
    #  真实模式（实验性，大概率被拦）
    # ----------------------------------------------------------------
    def _real_collect(self, keyword: str, city: str) -> list[RawPost]:
        """尝试爬取小红书搜索结果

        注意: 小红书反爬严格，此方法大概率失败。
        成功需要:
          1. 有效的cookie（登录态）
          2. 正确的签名参数（X-s, X-t等）
        """
        print(f"  [xiaohongshu] 尝试真实爬取: {keyword}")

        if not self.cookie:
            print("  [xiaohongshu] 未提供cookie，真实模式可能失败")
            print("  [xiaohongshu] 建议: 设置cookie参数或改用stub模式")

        # 小红书网页版搜索API（需要签名，此处仅尝试基本请求）
        search_url = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"
        payload = {
            "keyword": f"{city} {keyword} 租房",
            "page": 1,
            "page_size": 20,
            "search_id": "",
            "sort": "general",
            "note_type": 0,
        }

        try:
            resp = self.session.post(search_url, json=payload, timeout=15)
            print(f"  [xiaohongshu] 响应状态: {resp.status_code}")

            if resp.status_code != 200:
                print(f"  [xiaohongshu] 请求失败 (HTTP {resp.status_code})")
                print(f"  [xiaohongshu] 可能原因: 需要cookie/签名错误/被反爬拦截")
                return []

            data = resp.json()
            if not data.get("success"):
                print(f"  [xiaohongshu] API返回失败: {data.get('msg', 'unknown')}")
                return []

            # 解析笔记列表
            notes = data.get("data", {}).get("items", [])
            print(f"  [xiaohongshu] 获取到 {len(notes)} 条笔记")

            posts = []
            ts = time.strftime("%Y-%m-%dT%H:%M:%S")

            for note in notes[:self.max_posts]:
                note_id = note.get("id", "")
                title = note.get("note_card", {}).get("title", "")
                desc = note.get("note_card", {}).get("desc", "")
                user = note.get("note_card", {}).get("user", {}).get("nickname", "")

                if not title and not desc:
                    continue

                post = RawPost(
                    platform="xiaohongshu",
                    post_id=f"xhs_{note_id}",
                    url=f"https://www.xiaohongshu.com/explore/{note_id}",
                    title=title,
                    content=desc,
                    comments="",  # 小红书评论需单独请求
                    author=user,
                    published_at=ts,
                    collected_at=ts,
                )
                posts.append(post)

            return posts

        except Exception as e:
            print(f"  [xiaohongshu] 爬取异常: {e}")
            return []
