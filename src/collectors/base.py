# -*- coding: utf-8 -*-
"""采集器基类"""
from abc import ABC, abstractmethod
from src.models import RawPost


class BaseCollector(ABC):
    """平台采集器基类"""

    platform_name: str = "base"

    @abstractmethod
    def collect(self, keyword: str, city: str) -> list[RawPost]:
        """按关键词采集帖子

        Args:
            keyword: 搜索关键词 (如 "西二旗 租房")
            city: 城市

        Returns:
            list[RawPost]
        """
        ...
