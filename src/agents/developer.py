# -*- coding: utf-8 -*-
"""开发Agent — 执行采集计划，从帖子中提取结构化信息

核心职责:
  1. collect(): 调用采集器，按关键词爬取帖子
  2. extract(): 用LLM从帖子文本中提取结构化房源信息

提取Loop的核心: 提取→验证→(反馈)→重新提取
"""
import json
import time

from src.agents.base import BaseAgent
from src.models import (
    CollectionTask, CollectionPlan, RawPost, Listing,
    AcceptanceCriteria, Platform,
)
from src.llm import LLMClient


class DeveloperAgent(BaseAgent):
    name = "developer"

    # 提取Prompt模板
    SYSTEM_PROMPT = """你是一个租房信息提取专家。从社交平台帖子中提取结构化租房信息。

规则:
1. 只提取文本中明确出现的信息，不要猜测
2. 缺失字段填null
3. price_monthly: 月租金，纯数字(元)，不含押金
4. rental_subtype: 转租/直租/找室友/招租/无关
5. is_rental: 帖子是否在出租房子(true/false)
6. contact: 微信号/手机号/豆瓣私信等
7. 如果帖子不是租房相关，is_rental设为false，其他字段全null"""

    EXTRACTION_SCHEMA = """请以JSON格式回复:
{
  "is_rental": true/false,
  "rental_subtype": "转租/直租/找室友/招租/无关",
  "title": "帖子标题或你拟的简短标题",
  "price_monthly": 数字或null,
  "deposit_method": "押一付三/押一付一等",
  "city": "城市",
  "district": "区/县",
  "neighborhood": "小区名或地标",
  "address_raw": "原始地址描述",
  "room_type": "整租/合租/单间/公寓",
  "layout": "如2室1厅",
  "area_sqm": 数字或null,
  "floor": "如6/18层",
  "contact": "联系方式",
  "available_from": "可入住日期",
  "highlights": "亮点，逗号分隔"
}"""

    def __init__(self, llm: LLMClient = None):
        super().__init__()
        self.llm = llm
        self._collectors = {}

    def register_collector(self, platform: Platform, collector):
        """注册平台采集器"""
        self._collectors[platform] = collector

    # ----------------------------------------------------------------
    #  采集
    # ----------------------------------------------------------------
    def collect(self, task: CollectionTask) -> list[RawPost]:
        """执行采集任务"""
        collector = self._collectors.get(task.platform)
        if not collector:
            self._log(f"无 {task.platform.value} 采集器，跳过")
            return []

        all_posts = []
        for kw in task.keywords:
            self._log(f"采集: {task.platform.value} / '{kw}'")
            try:
                posts = collector.collect(kw, task.city)
                all_posts.extend(posts)
                self._log(f"  获取 {len(posts)} 条帖子")
            except Exception as e:
                self._log(f"  采集失败: {e}")

        # 简单去重 by post_id
        seen = set()
        unique = []
        for p in all_posts:
            if p.post_id and p.post_id not in seen:
                seen.add(p.post_id)
                unique.append(p)
            elif not p.post_id:
                unique.append(p)

        self._log(f"采集完成: {len(unique)}条 (去重前{len(all_posts)})")
        return unique

    # ----------------------------------------------------------------
    #  提取 (LLM驱动)
    # ----------------------------------------------------------------
    def extract(self, post: RawPost,
                criteria: AcceptanceCriteria) -> Listing:
        """从帖子中提取结构化房源信息

        如果post有validation_feedback，会加入prompt让LLM针对性补充
        """
        if not self.llm:
            self._log("无LLM客户端，跳过提取")
            return Listing(title=post.title, source_platform=post.platform)

        # 构造消息
        user_msg = f"帖子标题: {post.title}\n帖子内容: {post.content}"

        if post.comments:
            user_msg += f"\n\n评论区:\n{post.comments}"

        # 加入验收标准
        system_msg = self.SYSTEM_PROMPT + "\n\n" + criteria.to_prompt()

        # 如果有上一轮的验证反馈，加入prompt
        if post.validation_feedback:
            system_msg += (f"\n\n上一轮验证反馈(请针对性补充):\n"
                           f"{post.validation_feedback}")

        user_msg += "\n\n" + self.EXTRACTION_SCHEMA

        try:
            result = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": user_msg},
                ],
                temperature=0.1,
            )
        except Exception as e:
            self._log(f"LLM提取失败: {e}")
            return Listing(
                title=post.title,
                source_platform=post.platform,
                source_url=post.url,
                confidence=0.0,
            )

        # 构造Listing
        listing = Listing(
            title=result.get("title", post.title),
            description=post.content[:200],
            price_monthly=result.get("price_monthly"),
            deposit_method=result.get("deposit_method", ""),
            city=result.get("city", ""),
            district=result.get("district", ""),
            neighborhood=result.get("neighborhood", ""),
            address_raw=result.get("address_raw", ""),
            room_type=result.get("room_type", ""),
            layout=result.get("layout", ""),
            area_sqm=result.get("area_sqm"),
            floor=result.get("floor", ""),
            contact=result.get("contact", ""),
            available_from=result.get("available_from", ""),
            highlights=result.get("highlights", ""),
            source_platform=post.platform,
            source_url=post.url,
            is_rental=result.get("is_rental", False),
            rental_subtype=result.get("rental_subtype", ""),
            confidence=0.5,  # 初始置信度，验证通过后提高
        )

        return listing
