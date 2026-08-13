# -*- coding: utf-8 -*-
"""Agent基类 — 共享工具方法"""
from src.models import (
    UserRequirement, CollectionPlan, RawPost, Listing,
    AcceptanceCriteria, ValidationResult,
)


class BaseAgent:
    """三个Agent的基类，提供日志和共享工具"""

    name: str = "base"

    def __init__(self):
        self._log_lines = []

    def _log(self, msg: str):
        """内部日志"""
        self._log_lines.append(msg)
        print(f"  [{self.name}] {msg}")

    @property
    def logs(self):
        return self._log_lines

    def reset_logs(self):
        self._log_lines = []
