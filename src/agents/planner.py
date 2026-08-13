# -*- coding: utf-8 -*-
"""规划师Agent — 接收需求，拆解目标，生成采集计划

刻意不进入技术细节（怎么爬、怎么提取），只关心:
  1. 算出可行域（用户能住哪些区域）
  2. 搜索可行站点周边小区（高德POI）
  3. 生成采集计划（哪些平台、搜什么关键词）
"""
from src.agents.base import BaseAgent
from src.models import (
    UserRequirement, CollectionPlan, CollectionTask,
    ViableStation, Platform,
)
from src.feasible_domain import FeasibleDomain


class PlannerAgent(BaseAgent):
    name = "planner"

    def __init__(self, feasible_domain: FeasibleDomain):
        super().__init__()
        self.fd = feasible_domain

    def plan(self, requirement: UserRequirement,
             progress_callback=None) -> CollectionPlan:
        """规划: 需求 → 可行域 → 小区搜索 → 采集计划

        流程:
          1. 调用可行域计算器，得到可达地铁站清单
          2. 对每个可行站点，搜索周边2km内小区（高德POI）
          3. 用小区名生成搜索关键词（比站名更精确）
          4. 生成采集任务清单
        """
        self._log(f"接收需求: {requirement.city}, "
                  f"工作={requirement.work_address}, "
                  f"通勤<={requirement.max_commute_min}min")

        # ---- Step 1: 可行域计算 ----
        self._log("计算可行域...")
        fd_result = self.fd.calculate(
            city=requirement.city,
            work_address=requirement.work_address,
            max_commute_min=requirement.max_commute_min,
            budget_min=requirement.budget_min,
            budget_max=requirement.budget_max,
            progress_callback=progress_callback,
        )

        viable = fd_result["viable_stations"]
        self._log(f"可行域: {len(viable)}个站点")

        if not viable:
            self._log("警告: 可行域为空，无法生成采集计划")
            return CollectionPlan(
                tasks=[], viable_stations=[],
                work_location=fd_result["work_location"],
                budget={"min": requirement.budget_min,
                        "max": requirement.budget_max},
            )

        # ---- Step 2: 搜索站点周边小区 ----
        self._log("搜索站点周边小区...")
        all_xiaoqu = []
        seen_xiaoqu = set()

        for station in viable:
            name = station["name"]
            lng = station.get("lng") or station.get("longitude")
            lat = station.get("lat") or station.get("latitude")

            if not lng or not lat:
                self._log(f"  {name}: 无坐标，跳过小区搜索")
                continue

            # 搜索周边2km内小区，最多10个
            xiaoqu_list = self.fd.gaode.search_xiaoqu(
                lng, lat, radius=2000, max_count=10)

            if xiaoqu_list:
                self._log(f"  {name}: {len(xiaoqu_list)}个小区")
                for xq in xiaoqu_list:
                    xq_name = xq["name"]
                    if xq_name not in seen_xiaoqu:
                        seen_xiaoqu.add(xq_name)
                        all_xiaoqu.append({
                            "name": xq_name,
                            "station": name,
                            "distance": xq["distance"],
                        })
            else:
                self._log(f"  {name}: 无小区数据，用站名兜底")

        self._log(f"共获取 {len(all_xiaoqu)} 个不重复小区")

        # ---- Step 3: 生成关键词 ----
        # 优先用小区名（更精确），站名作为补充
        keyword_sets = []

        # 小区名关键词（前15个，避免太多）
        for xq in all_xiaoqu[:15]:
            keyword_sets.append(xq["name"])

        # 站名关键词（兜底，如果小区太少）
        station_names = [s["name"] for s in viable]
        for name in station_names:
            if name not in keyword_sets:
                keyword_sets.append(name)

        # 去重
        keyword_sets = list(dict.fromkeys(keyword_sets))

        self._log(f"生成关键词: {len(keyword_sets)}组 "
                  f"(小区{len(all_xiaoqu)}+站点{len(viable)})")

        # ---- Step 4: 生成采集任务 ----
        # 豆瓣 + 小红书双平台采集
        tasks = [
            CollectionTask(
                platform=Platform.DOUBAN,
                keywords=keyword_sets,
                city=requirement.city,
            ),
            CollectionTask(
                platform=Platform.XIAOHONGSHU,
                keywords=keyword_sets,
                city=requirement.city,
            ),
        ]

        plan = CollectionPlan(
            tasks=tasks,
            viable_stations=viable,
            work_location=fd_result["work_location"],
            budget={"min": requirement.budget_min,
                    "max": requirement.budget_max},
        )

        self._log(f"采集计划: {len(tasks)}个平台, "
                  f"共{len(keyword_sets)}组关键词")
        return plan
