# -*- coding: utf-8 -*-
"""数据模型 — 贯穿整个系统的数据结构"""
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Platform(str, Enum):
    DOUBAN = "douban"
    XIAOHONGSHU = "xiaohongshu"
    WECHAT = "wechat"
    XIANYU = "xianyu"


@dataclass
class UserRequirement:
    """用户需求 — 系统的起点"""
    city: str
    work_address: str
    max_commute_min: int
    budget_min: Optional[int] = None
    budget_max: Optional[int] = None


@dataclass
class ViableStation:
    """可行域内的一个地铁站"""
    name: str
    lng: float
    lat: float
    commute_min: int
    distance_km: float
    search_keywords: str


@dataclass
class CollectionTask:
    """一个采集任务"""
    platform: Platform
    keywords: list[str]
    city: str


@dataclass
class CollectionPlan:
    """规划师生成的采集计划"""
    tasks: list[CollectionTask]
    viable_stations: list[dict]       # 可行域站点清单
    work_location: dict              # 工作地点坐标
    budget: dict


@dataclass
class RawPost:
    """采集到的原始帖子"""
    platform: str
    post_id: str = ""
    url: str = ""
    title: str = ""
    content: str = ""
    comments: str = ""               # 评论文本 (拼接)
    author: str = ""
    published_at: str = ""
    collected_at: str = ""
    validation_feedback: str = ""    # 上一轮验证的反馈，供LLM重新提取时参考


@dataclass
class Listing:
    """从帖子中提取的结构化房源"""
    # 基础信息
    title: str = ""
    description: str = ""

    # 价格
    price_monthly: Optional[int] = None
    deposit_method: str = ""

    # 位置
    city: str = ""
    district: str = ""
    neighborhood: str = ""
    address_raw: str = ""
    address_std: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None

    # 房屋
    room_type: str = ""               # 整租/合租/单间
    layout: str = ""                  # 2室1厅
    area_sqm: Optional[float] = None
    floor: str = ""

    # 联系
    contact: str = ""
    available_from: str = ""
    highlights: str = ""

    # 来源
    source_platform: str = ""
    source_url: str = ""
    is_from_comment: bool = False

    # AI处理
    confidence: float = 0.0
    is_rental: bool = True
    rental_subtype: str = ""         # 转租/直租/找室友
    ai_summary: str = ""

    # 提取过程
    extraction_attempts: int = 0
    validation_feedback: str = ""    # 上一轮验证的反馈


@dataclass
class AcceptanceCriteria:
    """评判器定义的验收标准 — 开发Agent提取前必须同意"""
    required_fields: list[str]       # 必填字段
    price_range: tuple               # (min, max) 或 None
    viable_station_names: set        # 可行域站点名集合
    city: str
    rules_description: str = ""     # 人类可读的规则描述

    def to_prompt(self) -> str:
        """转为LLM prompt片段"""
        lines = ["验收标准:"]
        lines.append(f"  1. 必须提取以下字段: {', '.join(self.required_fields)}")
        if self.price_range[0]:
            lines.append(f"  2. 价格必须在 {self.price_range[0]}-{self.price_range[1]} 元/月")
        lines.append(f"  3. 地址必须与以下站点相关: {', '.join(list(self.viable_station_names)[:10])}")
        lines.append(f"  4. 城市必须是: {self.city}")
        lines.append(f"  5. 缺失字段填null，不要猜测")
        return "\n".join(lines)


@dataclass
class ValidationResult:
    """验证结果"""
    passed: bool
    score: float                     # 0-1
    feedback: str = ""               # 给开发Agent的反馈
    failed_rules: list[str] = field(default_factory=list)
