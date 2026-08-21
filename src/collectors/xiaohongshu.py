# -*- coding: utf-8 -*-
"""小红书租房信息采集器 — stub + Playwright 真实模式

真实模式基于 Playwright 驱动本机 Chrome:
    - 签名(X-s/X-t)由页面JS自动生成，无需逆向
    - 登录态复用 login_xhs.py 生成的 data/xhs_state.json
    - state文件缺失/过期时自动回退到未登录搜索（部分内容仍可见）

首次使用:
    .venv/bin/python login_xhs.py   # 扫码一次，保存cookie
"""
import os
import random
import re
import time

from src.collectors.base import BaseCollector
from src.models import RawPost

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
STATE_PATH = os.path.join(BASE_DIR, "data", "xhs_state.json")


class XiaohongshuCollector(BaseCollector):
    """小红书租房信息采集器（Playwright 实现）"""

    platform_name = "xiaohongshu"

    def __init__(self, use_stub: bool = True,
                 max_posts: int = 10,
                 state_path: str = STATE_PATH,
                 headless: bool = True,
                 timeout_ms: int = 20000,
                 detail_delay: tuple = (5, 12),
                 scroll_delay: tuple = (2, 4),
                 search_suffix: str = "租房"):
        """
        detail_delay: 相邻两个笔记详情之间的随机停顿秒数(下限,上限)
        scroll_delay: 每次滚动加载之间的随机停顿秒数
        search_suffix: 自动拼到关键词后的后缀, 如"北京 西二旗 租房";
                       搜索"房价分布"类帖子时传""避免污染结果
        """
        self.use_stub = use_stub
        self.max_posts = max_posts
        self.state_path = state_path
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.detail_delay = detail_delay
        self.scroll_delay = scroll_delay
        self.search_suffix = search_suffix

    def collect(self, keyword: str, city: str) -> list:
        if self.use_stub:
            return self._stub_collect(keyword, city)
        return self._real_collect(keyword, city)

    # ----------------------------------------------------------------
    #  Stub模式（保留原有模拟数据，供Loop离线测试）
    # ----------------------------------------------------------------
    def _stub_collect(self, keyword: str, city: str) -> list:
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
                title="【转租】回龙观地铁口 两居室合租 女生优先",
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
                title="【房东直租】龙泽苑 整租一居室 精装修",
                content=("龙泽地铁站5分钟，小区新装修，环境优雅。\n"
                         "整租一居室，50平，南北通透，采光极佳。\n"
                         "月租3500，押一付三，长租优惠。\n"
                         "房东直租，无中介费。联系：电话 13800138000"),
                comments="房子还在吗？\n可以养猫吗？",
                author="房东阿姨",
                published_at=ts,
                collected_at=ts,
            ),
        ]
        return posts[:self.max_posts]

    # ----------------------------------------------------------------
    #  Playwright 真实模式
    # ----------------------------------------------------------------
    def _real_collect(self, keyword: str, city: str) -> list:
        from playwright.sync_api import sync_playwright

        has_state = os.path.exists(self.state_path)
        if not has_state:
            print("  [xiaohongshu] 未找到登录态 data/xhs_state.json，"
                  "以未登录模式尝试（结果可能不全）")
            print("  [xiaohongshu] 提示: 运行 .venv/bin/python login_xhs.py 扫码登录")

        suffix = self.search_suffix
        if suffix:
            search_term = f"{city} {keyword} {suffix}"
        else:
            # 关键词已含完整短语(如"北京 房价分布"), 直接用
            search_term = keyword
        print(f"  [xiaohongshu] Playwright 搜索: {search_term}")

        posts = []
        with sync_playwright() as p:
            browser = p.chromium.launch(
                channel="chrome",
                headless=self.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            ctx_kw = {
                "viewport": {"width": 1280, "height": 800},
                "user_agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X "
                               "10_15_7) AppleWebKit/537.36 (KHTML, like "
                               "Gecko) Chrome/120.0.0.0 Safari/537.36"),
                "locale": "zh-CN",
            }
            if has_state:
                ctx_kw["storage_state"] = self.state_path
            ctx = browser.new_context(**ctx_kw)
            ctx.set_default_timeout(self.timeout_ms)
            page = ctx.new_page()

            try:
                posts = self._search_and_parse(page, search_term)
            except Exception as e:
                print(f"  [xiaohongshu] 采集异常: {e}")
            finally:
                ctx.close()
                browser.close()

        # 登录态过期检测: 提示用户重新扫码
        if has_state and not posts:
            print("  [xiaohongshu] 0条结果，登录态可能已过期，"
                  "请重新运行 login_xhs.py")
        print(f"  [xiaohongshu] 共采集 {len(posts)} 条")
        return posts[:self.max_posts]

    def _search_and_parse(self, page, search_term: str) -> list:
        from urllib.parse import quote

        url = (f"https://www.xiaohongshu.com/search_result?"
               f"keyword={quote(search_term)}&source=web_explore_feed")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        # 登录弹窗处理: 关闭遮罩（未登录搜索仍可看部分结果）
        try:
            close = page.locator(".close-button, [class*='close']").first
            if close.is_visible(timeout=2000):
                close.click()
                page.wait_for_timeout(1000)
        except Exception:
            pass

        # 等待笔记卡片
        page.wait_for_selector("section.note-item, [data-v-a264b01a]",
                               timeout=self.timeout_ms)
        # 缓慢滚动加载(模拟真人浏览节奏)
        for _ in range(2):
            page.mouse.wheel(0, random.randint(800, 1500))
            page.wait_for_timeout(random.uniform(*self.scroll_delay) * 1000)

        cards = page.locator("section.note-item").all()
        print(f"  [xiaohongshu] 搜索页卡片数: {len(cards)}")

        # 按索引遍历卡片: 每轮重新定位(虚拟列表会刷新, 固定handle会错位)
        posts = []
        seen_ids = set()
        idx = 0
        empty_streak = 0
        cards_total = page.locator("section.note-item").count()
        while len(posts) < self.max_posts and idx < cards_total and empty_streak < 8:
            try:
                card = page.locator("section.note-item").nth(idx)
                link = card.locator("a.cover, a[href*='/search_result/'], "
                                    "a[href*='/explore/']").first
                href = link.get_attribute("href") or ""
                m = re.search(r"/(?:explore|search_result)/([0-9a-f]+)", href)
                note_id = m.group(1) if m else ""
                if not note_id or note_id in seen_ids:
                    idx += 1
                    continue
                seen_ids.add(note_id)

                # 卡片标题先做相关性过滤, 非租房内容不点开
                card_title = ""
                t_el = card.locator(".title, .footer .title").first
                if t_el.count():
                    card_title = t_el.inner_text(timeout=2000).strip()
                if not self._is_rental_related(card_title):
                    idx += 1
                    continue

                detail = self._open_note_modal(page, card)
                content = detail.get("content", "")
                if content and self._is_rental_related(
                        detail.get("title", "") + " " + content):
                    posts.append(RawPost(
                        platform="xiaohongshu",
                        post_id=f"xhs_{note_id}",
                        url=f"https://www.xiaohongshu.com/explore/{note_id}",
                        title=detail.get("title", "") or card_title,
                        content=content,
                        comments=detail.get("comments", ""),
                        author=detail.get("author", ""),
                        published_at=detail.get("published_at", ""),
                        collected_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                    ))
                    empty_streak = 0
                else:
                    empty_streak += 1
                idx += 1
                # 笔记间隔: 长随机停顿防风控
                time.sleep(random.uniform(*self.detail_delay))
            except Exception:
                idx += 1
                continue
        return posts

    @staticmethod
    def _is_rental_related(text: str) -> bool:
        if not text:
            return False
        return bool(re.search(r"租|房|室友|转租|整租|合租|房东|押一|月租",
                              text))

    def _open_note_modal(self, page, card) -> dict:
        """点击卡片在当前页打开详情弹窗并提取内容，完毕后关闭"""
        detail = {"title": "", "content": "", "comments": "",
                  "author": "", "published_at": ""}
        try:
            card.click()
            # 等详情弹窗出现(没出现则放弃这条)
            page.wait_for_selector(".note-detail-mask, #detail-title",
                                   timeout=8000)
            page.wait_for_timeout(random.uniform(1000, 2000))

            # 弹窗内的登录提示再次尝试关闭
            try:
                close = page.locator(".close-button").first
                if close.is_visible(timeout=1500):
                    close.click()
                    page.wait_for_timeout(800)
            except Exception:
                pass

            t = page.locator("#detail-title, .note-detail-mask .title").first
            if t.count():
                detail["title"] = t.inner_text(timeout=3000).strip()

            c = page.locator("#detail-desc, .note-detail-mask .desc").first
            if c.count():
                detail["content"] = c.inner_text(timeout=3000).strip()

            a = page.locator(".username, .author .name").first
            if a.count():
                detail["author"] = a.inner_text(timeout=3000).strip()

            d = page.locator(".date, .bottom-container .date").first
            if d.count():
                detail["published_at"] = d.inner_text(
                    timeout=3000).strip().replace("编辑于 ", "")

            # 评论: 滚动弹窗评论区
            try:
                comment_panel = page.locator(
                    ".comments-container, .note-scroller").first
                if comment_panel.count():
                    comment_panel.hover()
                    for _ in range(2):
                        page.mouse.wheel(0, 600)
                        page.wait_for_timeout(random.uniform(800, 1500))
            except Exception:
                pass

            items = page.locator(".comment-item .content").all()
            comments = []
            for item in items[:10]:
                try:
                    comments.append(item.inner_text(timeout=1000).strip())
                except Exception:
                    continue
            detail["comments"] = "\n".join(comments)
        except Exception as e:
            print(f"  [xiaohongshu] 详情弹窗提取失败: {e}")
        finally:
            # 关闭弹窗回到搜索结果
            try:
                mask = page.locator(".note-detail-mask").first
                if mask.count():
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(random.uniform(800, 1500))
            except Exception:
                pass
        return detail
