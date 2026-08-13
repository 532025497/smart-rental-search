# -*- coding: utf-8 -*-
"""评判器Agent — 定义验收标准，真实验证，反馈给开发Agent

核心原则(来自Loop文档):
  1. 开发前先定义验收标准(不急着开发)
  2. 评判器不只读字段，要真实验证(地址能否定位? 价格是否合理?)
  3. 验证不过就打回，让开发Agent重新提取
"""
from src.agents.base import BaseAgent
from src.models import (
    UserRequirement, CollectionPlan, Listing,
    AcceptanceCriteria, ValidationResult,
)


class EvaluatorAgent(BaseAgent):
    name = "evaluator"

    # 必填字段
    REQUIRED_FIELDS = [
        "is_rental",
        "price_monthly",
        "city",
        "address_raw",
        "room_type",
    ]

    def define_criteria(self, requirement: UserRequirement,
                        plan: CollectionPlan) -> AcceptanceCriteria:
        """定义验收标准 — 在开发Agent提取前就确定

        这是Loop文档的核心: "开发前先谈清验收标准"
        """
        station_names = set()
        for s in plan.viable_stations:
            station_names.add(s["name"])

        price_range = (requirement.budget_min, requirement.budget_max)

        rules = []
        rules.append(f"必填字段: {', '.join(self.REQUIRED_FIELDS)}")
        if price_range[0]:
            rules.append(f"价格在 {price_range[0]}-{price_range[1]} 元/月")
        rules.append(f"地址与以下站点相关: "
                     f"{', '.join(list(station_names)[:8])}")
        rules.append(f"城市必须是: {requirement.city}")
        rules.append("is_rental=false的帖子直接丢弃")
        rules.append("缺失字段填null，不要猜测")

        criteria = AcceptanceCriteria(
            required_fields=self.REQUIRED_FIELDS,
            price_range=price_range,
            viable_station_names=station_names,
            city=requirement.city,
            rules_description="\n".join(f"  {i+1}. {r}"
                                        for i, r in enumerate(rules)),
        )

        self._log(f"定义验收标准: {len(self.REQUIRED_FIELDS)}个必填字段, "
                  f"{len(station_names)}个可行站点")
        return criteria

    def validate(self, listing: Listing,
                 criteria: AcceptanceCriteria,
                 plan: CollectionPlan) -> ValidationResult:
        """验证一条房源 — 真实测试，不是只读字段

        检查项:
          1. 是否为租房帖 (is_rental)
          2. 必填字段是否完整
          3. 价格是否在预算内
          4. 地址是否在可行域内 (关键词匹配)
          5. 城市是否正确
        """
        feedback_parts = []
        failed = []
        score = 1.0

        # Rule 1: is_rental
        if not listing.is_rental:
            return ValidationResult(
                passed=False, score=0.0,
                feedback="帖子非租房相关，丢弃",
                failed_rules=["is_rental=false"],
            )

        # Rule 2: 必填字段
        for field_name in criteria.required_fields:
            value = getattr(listing, field_name, None)
            if value is None or value == "" or value is False:
                feedback_parts.append(f"字段'{field_name}'缺失")
                failed.append(f"missing:{field_name}")
                score -= 0.15

        # Rule 3: 价格范围
        # 高于上限: 硬性拒绝(租不起)
        # 低于下限: 软性标记(可能捡漏,但需警惕虚假信息)
        if criteria.price_range[0] and listing.price_monthly:
            pmin, pmax = criteria.price_range
            if listing.price_monthly > pmax:
                feedback_parts.append(
                    f"价格{listing.price_monthly}超出预算上限{pmax}")
                failed.append("price_over_budget")
                score -= 0.3
            elif listing.price_monthly < pmin:
                feedback_parts.append(
                    f"价格{listing.price_monthly}低于预算下限{pmin},"
                    f"可能是好 deal 但需警惕虚假信息")
                score -= 0.05  # 轻微扣分,不hard fail

        # Rule 4: 地址在可行域内
        # 关键词匹配: 检查address_raw/neighborhood是否包含可行站点名
        addr_text = (f"{listing.address_raw} {listing.neighborhood} "
                     f"{listing.district}").lower()
        matched = False
        for name in criteria.viable_station_names:
            if name and name.lower() in addr_text:
                matched = True
                break

        if not matched and addr_text.strip():
            feedback_parts.append(
                f"地址'{listing.address_raw}'不在可行域内，"
                f"请确认是否包含以下站点: "
                f"{', '.join(list(criteria.viable_station_names)[:5])}")
            failed.append("address_not_in_domain")
            score -= 0.25

        # Rule 5: 城市匹配
        if listing.city and criteria.city:
            if criteria.city not in listing.city:
                feedback_parts.append(
                    f"城市'{listing.city}'与目标'{criteria.city}'不符")
                failed.append("city_mismatch")
                score -= 0.2

        score = max(0.0, score)
        passed = score >= 0.6 and not any(
            "missing" in f for f in failed
        )

        feedback = "; ".join(feedback_parts) if feedback_parts else "全部通过"

        return ValidationResult(
            passed=passed,
            score=score,
            feedback=feedback,
            failed_rules=failed,
        )

    def rank(self, listings: list[Listing],
             requirement: UserRequirement) -> list[Listing]:
        """最终排序 — 按综合评分"""
        for li in listings:
            score = li.confidence
            # 价格在预算内加分
            if li.price_monthly and requirement.budget_min:
                mid = (requirement.budget_min + requirement.budget_max) / 2
                if requirement.budget_min <= li.price_monthly <= requirement.budget_max:
                    score += 0.2
                # 越接近预算下限越好(性价比)
                ratio = li.price_monthly / mid if mid else 1
                score += max(0, 0.1 * (2 - ratio))
            # 信息完整度
            filled = sum(1 for f in ["price_monthly", "area_sqm", "layout",
                                     "contact", "available_from"]
                        if getattr(li, f, None))
            score += filled * 0.03
            li.confidence = min(1.0, score)

        listings.sort(key=lambda x: x.confidence, reverse=True)
        return listings
