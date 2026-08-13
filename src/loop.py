# -*- coding: utf-8 -*-
"""主循环协调器 — 规划师→开发→评判器 三方协作Loop

核心流程(来自Loop文档):
  Phase 1: 规划师生成采集计划 (调用可行域计算器)
  Phase 2: 评判器定义验收标准 (开发前先谈清标准)
  Phase 3: 采集→提取→验证→(打回重提取)循环
  Phase 4: 排序输出

每一轮提取-验证是一个Loop:
  开发提取 → 评判验证 → 通过? 
    → YES: 入库
    → NO:  反馈写回帖子 → 重新提取 → (最多N轮)
"""
import time
import json

from src.agents.planner import PlannerAgent
from src.agents.developer import DeveloperAgent
from src.agents.evaluator import EvaluatorAgent
from src.models import UserRequirement, Listing


class RentalSearchLoop:
    """租房搜索系统 — 多Agent协作主循环"""

    def __init__(self, planner: PlannerAgent,
                 developer: DeveloperAgent,
                 evaluator: EvaluatorAgent,
                 max_retries: int = 3):
        self.planner = planner
        self.developer = developer
        self.evaluator = evaluator
        self.max_retries = max_retries

    def run(self, requirement: UserRequirement,
            progress_callback=None) -> dict:
        """执行完整Loop

        Returns:
            {
                "listings": list[Listing],  # 排序后的房源
                "plan": CollectionPlan,
                "criteria": AcceptanceCriteria,
                "stats": {...},
                "logs": [...],
            }
        """
        all_logs = []
        stats = {
            "collected": 0,
            "extracted": 0,
            "validated": 0,
            "passed": 0,
            "retried": 0,
            "rejected": 0,
            "llm_calls": 0,
            "llm_tokens": 0,
        }

        # ==================== Phase 1: 规划 ====================
        print("\n[Phase 1] 规划师生成采集计划...")
        plan = self.planner.plan(requirement, progress_callback)
        all_logs.extend(self.planner.logs)

        if not plan.viable_stations:
            print("  可行域为空，无法继续")
            return {"listings": [], "plan": plan, "stats": stats,
                    "logs": all_logs}

        # ==================== Phase 2: 验收标准 ====================
        print("\n[Phase 2] 评判器定义验收标准...")
        criteria = self.evaluator.define_criteria(requirement, plan)
        all_logs.extend(self.evaluator.logs)
        print(f"  验收标准:\n{criteria.rules_description}")

        # LLM是房源帖子结构化提取所必需的；没有Key时仍返回完整通勤可行域。
        if not self.developer.llm:
            print("\n[Phase 3] 未配置LLM API Key，跳过房源提取")
            return {
                "listings": [],
                "plan": plan,
                "criteria": criteria,
                "stats": stats,
                "logs": all_logs,
            }

        # ==================== Phase 3: 采集+提取+验证Loop ====================
        print("\n[Phase 3] 开始采集+提取+验证循环...")

        all_listings = []

        for task in plan.tasks:
            # ---- 3a: 采集 ----
            raw_posts = self.developer.collect(task)
            stats["collected"] += len(raw_posts)
            all_logs.extend(self.developer.logs)

            if not raw_posts:
                continue

            # ---- 3b: 逐条提取+验证Loop ----
            for i, post in enumerate(raw_posts):
                tag = f"[{i+1}/{len(raw_posts)}]"
                print(f"\n  {tag} 提取: {post.title[:30]}...")

                best_listing = None
                best_score = 0

                for attempt in range(self.max_retries):
                    attempt_tag = f"    第{attempt+1}轮"

                    # 提取
                    listing = self.developer.extract(post, criteria)
                    listing.extraction_attempts = attempt + 1
                    stats["extracted"] += 1

                    if self.developer.llm:
                        stats["llm_calls"] = self.developer.llm.call_count
                        stats["llm_tokens"] = self.developer.llm.total_tokens

                    if not listing.is_rental:
                        print(f"  {attempt_tag} 非租房帖，跳过")
                        stats["rejected"] += 1
                        best_listing = None
                        break

                    # 验证
                    result = self.evaluator.validate(
                        listing, criteria, plan)
                    stats["validated"] += 1

                    print(f"  {attempt_tag} 验证: "
                          f"score={result.score:.2f} "
                          f"{'PASS' if result.passed else 'FAIL'}")
                    if result.failed_rules:
                        print(f"           失败: "
                              f"{', '.join(result.failed_rules)}")

                    if result.passed:
                        listing.confidence = result.score
                        best_listing = listing
                        best_score = result.score
                        stats["passed"] += 1
                        break
                    else:
                        if result.score > best_score:
                            best_listing = listing
                            best_score = result.score
                        if attempt < self.max_retries - 1:
                            # 写回反馈，供下一轮提取
                            post.validation_feedback = result.feedback
                            print(f"           反馈: {result.feedback[:60]}")
                            stats["retried"] += 1

                # Loop结束后: 收集最佳结果
                if best_listing:
                    if not best_listing.validation_feedback:
                        # 验证通过
                        best_listing.confidence = best_score
                    else:
                        # 最大重试后仍未通过，低置信度保留
                        best_listing.confidence = best_score * 0.4
                    all_listings.append(best_listing)

        all_logs.extend(self.developer.logs)

        # ==================== Phase 4: 排序 ====================
        print(f"\n[Phase 4] 排序输出...")
        ranked = self.evaluator.rank(all_listings, requirement)
        all_logs.extend(self.evaluator.logs)

        # 统计
        print(f"\n{'='*60}")
        print(f"  统计:")
        print(f"    采集帖子: {stats['collected']}")
        print(f"    LLM提取:  {stats['extracted']}次")
        print(f"    验证:     {stats['validated']}次")
        print(f"    通过:     {stats['passed']}条")
        print(f"    重试:     {stats['retried']}次")
        print(f"    丢弃:     {stats['rejected']}条")
        print(f"    最终房源: {len(ranked)}条")
        if stats["llm_calls"]:
            print(f"    LLM调用:  {stats['llm_calls']}次, "
                  f"{stats['llm_tokens']}tokens")
        print(f"{'='*60}")

        return {
            "listings": ranked,
            "plan": plan,
            "criteria": criteria,
            "stats": stats,
            "logs": all_logs,
        }
