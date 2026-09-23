"""分页演示数据：为「列表统一分页」（ADR-0024）的人工验收造出多页数据。

`app.db.seed` 是固定夹具（5 位客户、7 只产品、20 条规则），很多用例按精确数字断言，
改不得；本模块在它之上**叠加**演示规模的数据，与 `app.db.graph_demo_seed` 同一路子
——只为人工翻页存在、不参与任何断言，单独跑：

    python -m app.db.pagination_demo_seed          # 造数（先清后建）
    python -m app.db.pagination_demo_seed --purge  # 只清掉本模块造出来的行

每个分页列表都造到「默认页长 10 装不下」，且筛选与排序两种用法各有内容可翻：

| 列表 | 谁看得到 | 造了多少 |
|---|---|---|
| 客户目录 `/api/internal/customers` | 全部内部角色 | 新增 44 位客户（顾问/风控共 52，客户经理各约 26） |
| 风险测评历史 `customers/{id}/risk-assessments` | 全部内部角色 | 每位演示客户 25 条（含 1 条有效期内的） |
| 预警 / 风险关注 / 风控规则 | 全部内部角色 | 52 / 45 / 新增 12 条停用规则（共 32） |
| 工单 `/api/internal/work-orders` | 全部内部角色 | 44 张（四个状态齐全，含流转留痕） |
| 知识文档 `knowledge/documents` | 全部内部角色 | 40 篇（30 已入库 + 6 处理中 + 4 处理失败） |
| 分析历史 `analytics/history` | 全部内部角色 | 每位员工 45 条 |
| 历史会话 `conversations` | 全部内部角色 | 40 场（挂在 zhangc3 名下） |
| 投顾队列 / 审核历史 / 方案请求 | 仅理财顾问 | 32 / 57 / 45 |
| 操作建议进度 `customers/{id}/operation-advice` | 顾问 + 客户经理 | 52 条（挂在 zhangc3 名下） |
| 交易流水 `/api/customer/transactions` | 客户本人 | 103 笔（申赎转账充值各 25+，全量 5 页） |
| 我的建议 `/api/customer/operation-advice` | 客户本人 | 52 条（四个状态齐全） |
| 我的方案 `/api/customer/advisory/plans` | 客户本人 | 45 份已放行定稿 |
| 产品筛选 `/api/customer/products` | 客户本人 | 新增 50 只在售产品 |

**造出来的数据挂在哪几位客户身上**：客户侧的列表（流水、建议、方案、会话）全部挂在
基础种子里的 `zhangc3` 名下——他名下客户经理是 manager1、风险承受等级 C3、可用余额
充足，是演示里最顺手的那一位；内部侧的列表按需要分散到基础客户与新增客户上。

**先清后建，不是「不存在才插入」**：本模块的每一行都能被识别出来（编号前缀或标记
文本，见 `_purge`），重新执行等于把演示数据恢复成这一版。若用「不存在才插入」，
改条数之后上一轮多出来的行会留在库里，而它们与这一轮造出来的看起来一模一样。

清掉的只有本模块造的行：基础种子、回放数据，以及你在界面上操作产生的数据一律不动。
两处例外要说清——① 若你把某条演示建议「接受」了，那笔成交是受理侧写的**真实交易**，
它不带演示前缀，重跑不会清它；② 若你从演示预警派生过工单，那张工单会被一起清掉，
因为它的来源预警没了（外键）。

**几处已知的、不可避免的性质**（不是数据造坏了）：

- 演示的「待审」投顾内容不是由生成流程跑出来的，运行时里没有中断点，因此点「放行」
  会得到「审核状态已失效，请重新生成方案」——这与直接把原稿写进库的既有数据同性质，
  验收目标在这两页上是**列表与翻页**，不是审核动作本身；
- 演示流水是直接写三张表的，不走受理侧，因此不会改动持仓与余额，资产页的数字与流水
  条数不联动；
- 演示客户的风评记录全部按各自的画像等级补了一条**有效期内**的，于是 C1 到 C5 这几位
  客户都能进产品筛选页（在此之前 lisic2/zhangc3/zhaoc4 的测评早已过期，产品筛选会直接
  403「风险测评已过期」）。
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, TypedDict

from argon2 import PasswordHasher
from sqlalchemy import create_engine, delete, or_, select
from sqlalchemy.orm import Session

from app.db.models import (
    AdvisoryDraft,
    AdvisoryFinal,
    AdvisoryRequest,
    AdvisoryReview,
    AdvisoryReviewAudit,
    AnalyticsQueryAudit,
    ConversationArchive,
    Customer,
    CustomerProfile,
    Deposit,
    Employee,
    FundingAccount,
    KnowledgeMeta,
    OperationAdviceDecision,
    OperationAdviceDraft,
    Product,
    RiskAlert,
    RiskAssessment,
    RiskFocus,
    RiskRule,
    RiskRuleChange,
    SuitabilityDecision,
    Transaction,
    Transfer,
    WorkOrder,
    WorkOrderTransition,
)
from app.risk_monitoring.fields import FIELD_REGISTRY
from app.risk_monitoring.operators import OPERATOR_REGISTRY
from app.risk_monitoring.rules import RISK_RULE_SEEDS
from app.settings import get_settings

DEFAULT_PASSWORD = "Test@1234"

# 没有业务键的行靠这个标记认出来（预警的触发详情、风险关注的关注理由）。
MARK = "【分页演示】"

_USERNAME_PREFIX = "pgdemo"
_PRODUCT_PREFIX = "PGD"
_FLOW_PREFIX = "PGD"
_RULE_PREFIX = "PGDR"
_ORDER_PREFIX = "PGDWO"
_REQUEST_PREFIX = "PGDREQ"
_SESSION_PREFIX = "pgd-sess-"
_DOC_PREFIX = "pgd_demo/"
_THREAD_PREFIX = "pgd-"

DEMO_CUSTOMERS = 44
DEMO_PRODUCTS = 50
FLOW_PER_TYPE = 25
ALERTS = 52
FOCUS_RECORDS = 45
DISABLED_RULES = 12
WORK_ORDERS = 44
RELEASED_PLANS = 45
PENDING_PLANS = 20
PENDING_ADVICES = 12
REJECTED_PLANS = 12
ADVISORY_REQUESTS = 45
CUSTOMER_ADVICES = 52
CUSTOMER_SESSIONS = 40
ANALYTICS_PER_EMPLOYEE = 45
KNOWLEDGE_DOCUMENTS = 40

# 客户侧的演示数据统一挂在基础种子的这一位客户名下。
DEMO_CUSTOMER_USERNAME = "zhangc3"

_ADVISOR = "advisor1"
_MANAGER_ONE = "manager1"
_MANAGER_TWO = "manager2"
_RISK_OFFICER = "risk1"

_LEVELS = ("普通", "金卡", "白金", "钻石", "私行")
_LEVEL_RISK = {"普通": "C1", "金卡": "C2", "白金": "C3", "钻石": "C4", "私行": "C5"}
_SCORE_BY_LEVEL = {"C1": 18, "C2": 36, "C3": 55, "C4": 74, "C5": 92}

_LEVEL_TOTAL_ASSETS = {
    "普通": Decimal("68000.00"),
    "金卡": Decimal("260000.00"),
    "白金": Decimal("760000.00"),
    "钻石": Decimal("2400000.00"),
    "私行": Decimal("7800000.00"),
}
_LEVEL_INCOME = {
    "普通": "10万以下",
    "金卡": "10-30万",
    "白金": "30-50万",
    "钻石": "50-100万",
    "私行": "100万以上",
}
_LEVEL_EXPERIENCE = {
    "普通": "0-1年",
    "金卡": "1-3年",
    "白金": "3-5年",
    "钻石": "5-10年",
    "私行": "10年以上",
}
_LEVEL_TARGET = {
    "普通": {"股票": 10, "债券": 40, "现金": 50, "另类": 0},
    "金卡": {"股票": 20, "债券": 50, "现金": 25, "另类": 5},
    "白金": {"股票": 40, "债券": 35, "现金": 15, "另类": 10},
    "钻石": {"股票": 55, "债券": 25, "现金": 10, "另类": 10},
    "私行": {"股票": 70, "债券": 10, "现金": 5, "另类": 15},
}
_LEVEL_PREFERENCE = {
    "普通": {"基金": ["货币基金"]},
    "金卡": {"基金": ["债券基金"]},
    "白金": {"基金": ["混合基金"]},
    "钻石": {"基金": ["股票基金"]},
    "私行": {"基金": ["股票基金", "指数基金"]},
}
_LEVEL_BALANCE = {
    "普通": Decimal("26000.00"),
    "金卡": Decimal("180000.00"),
    "白金": Decimal("620000.00"),
    "钻石": Decimal("2100000.00"),
    "私行": Decimal("4600000.00"),
}

_SURNAMES = (
    "赵", "钱", "孙", "李", "周", "吴", "郑", "王", "冯", "陈", "褚", "卫",
    "蒋", "沈", "韩", "杨", "朱", "秦", "尤", "许", "何", "吕",
)
_GIVEN_NAMES = (
    "嘉禾", "子墨", "思远", "安然", "文博", "雅静", "志强", "晓峰",
    "若彤", "浩然", "梦琪", "俊杰",
)

# 产品类型与风险等级的搭配与基础种子一致：R1 货币、R2 债券、R3 混合/指数、R4 股票、R5 QDII。
_PRODUCT_TYPE_BY_RISK = {
    "R1": "货币基金",
    "R2": "债券基金",
    "R3": "混合基金",
    "R4": "股票基金",
    "R5": "QDII基金",
}

def _quarterly_dates(count: int, start: date) -> tuple[date, ...]:
    """从 `start` 起按季度推进的日期序列，确定性生成、不依赖当前时间。"""
    dates: list[date] = []
    year, month = start.year, start.month
    for _ in range(count):
        dates.append(date(year, month, 1))
        month += 3
        if month > 12:
            month -= 12
            year += 1
    return tuple(dates)


# 风评日期刻意避开基础种子的日期（2020-05-01 / 2021-06-20 / 2022-03-15 / 2019-09-20 …），
# 于是「清掉本模块造的那些」可以按 (客户, 日期) 精确判定。
_CURRENT_ASSESSMENT_DATE = date(2026, 9, 1)
_CURRENT_ASSESSMENT_VALID_UNTIL = date(2027, 9, 1)
_HISTORICAL_ASSESSMENT_DATES = _quarterly_dates(24, date(2019, 9, 1))
_ASSESSMENT_DATES = (*_HISTORICAL_ASSESSMENT_DATES, _CURRENT_ASSESSMENT_DATE)

# 流水按类型各占一个日期带：全量 5 页、按类型筛 2 页、按日期段筛也能筛出多页。
_PURCHASE_BASE = datetime(2026, 1, 1, 9, 30, 0)
_REDEEM_BASE = datetime(2026, 3, 1, 9, 30, 0)
_TRANSFER_BASE = datetime(2026, 5, 1, 9, 30, 0)
_DEPOSIT_BASE = datetime(2026, 7, 1, 9, 30, 0)
# 三条记录挤在同一秒：排序只到秒，靠「来源序号 + 行标识」兜底，人工翻页能验证它稳定。
_SAME_SECOND = datetime(2026, 9, 20, 10, 0, 0)

_FLOW_PRODUCT_CODE = "F000003"

_ANALYTICS_QUESTIONS: tuple[str, ...] = (
    "统计各风险等级的在售产品数量",
    "统计各客户分层的人数分布",
    "统计各预警等级的预警数量",
    "统计各产品类型的在售产品数量",
    "统计各风险承受等级的客户数量",
    "统计近 30 天的交易笔数",
    "统计各行业的底层资产数量",
    "统计每位客户经理名下的客户数量",
    "统计在售产品的平均起投金额",
    "统计各预警状态的数量",
    "统计各工单状态的工单数量",
    "统计各产品风险等级的平均费率",
    "统计各客户的总资产分布",
    "统计各交易类型的笔数",
    "统计各知识类型已入库的文档数量",
    "统计各投顾内容的审核状态数量",
    "统计各操作建议方向的数量",
    "统计各客户经理对应客户的持仓数量",
    "统计各产品的基金经理数量",
    "统计各风险等级产品的期限分布",
)

_DOC_TITLES = (
    "基金申购与赎回业务规则",
    "客户风险评估管理办法",
    "适当性管理实施细则",
    "反洗钱客户身份识别要求",
    "大额交易与可疑交易报告标准",
    "理财产品销售适当性指引",
    "客户信息保密管理规定",
    "投资者教育与适当性告知流程",
    "基金定投业务操作手册",
    "账户开立与变更业务规程",
    "客户投诉受理与处理规范",
    "净值型产品信息披露要求",
    "投资顾问服务管理办法",
    "产品风险等级评估方法",
    "客户画像与适当性匹配说明",
    "资金账户与可用余额说明",
    "交易确认与清算交收规则",
    "风险预警分级与处置指引",
    "工单流转与办结规范",
    "知识库文档入库与下架规范",
)

_ADVICE_REASONS = (
    "客户近期现金流充裕，建议将闲置资金配置到与风险承受等级匹配的混合型产品，提升组合的收益弹性。",
    "客户持仓集中度偏高，建议赎回部分仓位以降低单一产品占比，使配置回到目标比例附近。",
    "结合客户目标配置中债券仓位偏低的情况，建议分批申购债券型产品，平滑组合波动。",
    "客户对流动性有较高要求，建议以货币型产品承接短期闲置资金，兼顾流动性与收益。",
    "客户风险承受等级未发生变化，建议在当前配置基础上做小幅再平衡，避免风格漂移。",
    "客户持仓品种与本人产品偏好一致，建议按目标配置补齐现金类资产，保持组合的防御性。",
)

_PLAN_TILTS = ("均衡", "收益优先", "稳健优先")

_CHAT_PAIRS = (
    ("我有 50 万想买理财产品，有什么建议？", "您好，产品选择需要与您的风险承受等级匹配。您可以在「产品筛选」页看到与您等级相符的在售产品，也可以先完成风险测评以确认等级。"),
    ("风险测评多久需要重新做一次？", "风险测评结论的有效期为一年，到期后需要重新完成测评，系统会在有效期临近时提醒您。"),
    ("申购和赎回的手续费怎么算？", "手续费按产品披露的费率计算：申购时从成交金额中按费率计提，赎回时从赎回金额中扣除，具体费率以产品详情页披露的信息为准。"),
    ("我的持仓能不能看到底层资产？", "可以。在「我的资产」页展开持仓明细即可看到穿透后的底层资产与占比。"),
    ("产品风险等级和我的风险等级是一回事吗？", "不是。产品风险等级用 R1 到 R5 衡量产品自身的风险，风险承受等级用 C1 到 C5 衡量您能承受的风险，两者只在适当性匹配时比较。"),
    ("我可以在手机上操作赎回吗？", "可以。赎回在「交易」页的下单区域操作，赎回金额会按产品当前净值与费率计算。"),
    ("账户里突然收到一笔钱是什么原因？", "可能是充值入账或赎回成交的回款，您可以在「交易」页的交易流水里按类型与日期筛选核对。"),
    ("我没有收到风险提示短信？", "风险提示短信会在预警触发后发送到您预留的手机号，如果长时间未收到，建议核对预留手机号是否正确。"),
)

_WORK_ORDER_THEMES = (
    "客户对交易确认时效的疑问",
    "客户反馈产品收益与预期不符",
    "客户咨询赎回款到账时间",
    "客户经理转来的适当性复核",
    "客户投诉电话回访不满意",
    "客户咨询大额转账的合规要求",
    "客户反馈手机号变更未生效",
    "客户咨询风险测评结果的有效期",
    "客户对持仓集中度的风险提示有疑问",
    "客户咨询反洗钱信息补充要求",
)


class _Context(TypedDict):
    employees: dict[str, Employee]
    products: dict[str, Product]
    customers: dict[str, Customer]
    demo_customers: list[Customer]
    now: datetime


# ---------------------------------------------------------------- 造数入口


def seed_pagination_demo(database_url: str | None = None) -> None:
    url = database_url or get_settings().database_url
    engine = create_engine(url)
    hasher = PasswordHasher()
    password_hash = hasher.hash(DEFAULT_PASSWORD)
    try:
        with Session(engine) as session:
            _require_base_seed(session)
            _purge(session)
            now = datetime.now()
            context = _load_context(session, now)
            _seed_customers(session, context, password_hash)
            _seed_products(session, context)
            context = _load_context(session, now)
            _seed_flow_records(session, context)
            _seed_assessments(session, context)
            _seed_alerts_and_focus(session, context)
            _seed_disabled_rules(session)
            _seed_work_orders(session, context)
            _seed_advisory(session, context)
            _seed_operation_advice(session, context)
            _seed_conversations(session, context)
            _seed_analytics_history(session, context)
            _seed_knowledge_documents(session)
            session.commit()
            _report()
    finally:
        engine.dispose()


def purge_pagination_demo(database_url: str | None = None) -> None:
    url = database_url or get_settings().database_url
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            _purge(session)
            session.commit()
    finally:
        engine.dispose()


def _require_base_seed(session: Session) -> None:
    missing = [
        username
        for username in (_ADVISOR, _MANAGER_ONE, _MANAGER_TWO, _RISK_OFFICER, DEMO_CUSTOMER_USERNAME)
        if session.scalar(select(Employee.id).where(Employee.username == username)) is None
        and session.scalar(select(Customer.id).where(Customer.username == username)) is None
    ]
    if missing:
        raise RuntimeError(
            "基础种子还没跑：先执行 `python -m app.db.setup`，再跑本模块。缺少 " + "、".join(missing)
        )


def _load_context(session: Session, now: datetime) -> _Context:
    employees = {row.username: row for row in session.scalars(select(Employee)).all()}
    products = {row.product_code: row for row in session.scalars(select(Product)).all()}
    customers = {row.username: row for row in session.scalars(select(Customer)).all()}
    demo = [
        row for username, row in customers.items() if username.startswith(_USERNAME_PREFIX)
    ]
    demo.sort(key=lambda row: row.username)
    return {
        "employees": employees,
        "products": products,
        "customers": customers,
        "demo_customers": demo,
        "now": now,
    }


# ---------------------------------------------------------------- 清理


def _purge(session: Session) -> None:
    """清掉本模块造出来的行；基础种子与界面操作产生的数据一律不动。

    一律**先取标识再删**：MySQL 不允许在 DELETE 的子查询里再读同一张表（错误 1093），
    而删除顺序必须自下而上——外键会挡住顺序错了的那一步。
    """
    demo_customer_ids = list(
        session.scalars(
            select(Customer.id).where(Customer.username.like(f"{_USERNAME_PREFIX}%"))
        ).all()
    )
    base_customer_ids = list(
        session.scalars(
            select(Customer.id).where(~Customer.username.like(f"{_USERNAME_PREFIX}%"))
        ).all()
    )
    all_customer_ids = base_customer_ids + demo_customer_ids

    assessment_ids = list(
        session.scalars(
            select(RiskAssessment.id).where(
                RiskAssessment.customer_id.in_(all_customer_ids),
                RiskAssessment.assessment_date.in_(_ASSESSMENT_DATES),
            )
        ).all()
    )
    review_rows = session.execute(
        select(AdvisoryReview.id, AdvisoryReview.content_type, AdvisoryReview.content_ref).where(
            AdvisoryReview.thread_id.like(f"{_THREAD_PREFIX}%")
        )
    ).all()
    review_ids = [review_id for review_id, _type, _ref in review_rows]
    plan_draft_ids = [ref for _id, content_type, ref in review_rows if content_type == "方案"]
    advice_ids = [ref for _id, content_type, ref in review_rows if content_type == "操作建议"]
    alert_ids = list(
        session.scalars(
            select(RiskAlert.id).where(RiskAlert.trigger_detail.like(f"{MARK}%"))
        ).all()
    )
    order_ids = list(
        session.scalars(
            select(WorkOrder.id).where(
                or_(
                    WorkOrder.work_order_no.like(f"{_ORDER_PREFIX}%"),
                    WorkOrder.source_alert_id.in_(alert_ids),
                )
            )
        ).all()
    )
    rule_ids = list(
        session.scalars(select(RiskRule.id).where(RiskRule.rule_code.like(f"{_RULE_PREFIX}%"))).all()
    )
    product_ids = list(
        session.scalars(select(Product.id).where(Product.product_code.like(f"{_PRODUCT_PREFIX}%"))).all()
    )
    employee_ids = list(
        session.scalars(select(Employee.id).where(Employee.username.in_(
            (_ADVISOR, _MANAGER_ONE, _MANAGER_TWO, _RISK_OFFICER)
        ))).all()
    )

    session.execute(delete(WorkOrderTransition).where(WorkOrderTransition.work_order_id.in_(order_ids)))
    session.execute(delete(WorkOrder).where(WorkOrder.id.in_(order_ids)))
    session.execute(delete(RiskAlert).where(RiskAlert.id.in_(alert_ids)))
    session.execute(delete(RiskFocus).where(RiskFocus.reason.like(f"{MARK}%")))
    session.execute(delete(OperationAdviceDecision).where(OperationAdviceDecision.advice_id.in_(advice_ids)))
    session.execute(delete(AdvisoryReviewAudit).where(AdvisoryReviewAudit.review_id.in_(review_ids)))
    session.execute(delete(AdvisoryFinal).where(AdvisoryFinal.draft_id.in_(plan_draft_ids)))
    session.execute(delete(AdvisoryReview).where(AdvisoryReview.id.in_(review_ids)))
    session.execute(delete(OperationAdviceDraft).where(OperationAdviceDraft.id.in_(advice_ids)))
    session.execute(delete(AdvisoryDraft).where(AdvisoryDraft.id.in_(plan_draft_ids)))
    session.execute(delete(AdvisoryRequest).where(AdvisoryRequest.request_no.like(f"{_REQUEST_PREFIX}%")))
    session.execute(
        delete(ConversationArchive).where(ConversationArchive.session_id.like(f"{_SESSION_PREFIX}%"))
    )
    session.execute(
        delete(AnalyticsQueryAudit).where(
            AnalyticsQueryAudit.employee_id.in_(employee_ids),
            AnalyticsQueryAudit.question.in_(_ANALYTICS_QUESTIONS),
        )
    )
    session.execute(delete(KnowledgeMeta).where(KnowledgeMeta.source_file.like(f"{_DOC_PREFIX}%")))
    session.execute(delete(Transaction).where(Transaction.transaction_no.like(f"{_FLOW_PREFIX}%")))
    # 演示产品被买过时，那笔成交的 product_id 会挡住产品行的删除；产品本身要没了，
    # 这笔成交在流水里也读不出产品名（INNER JOIN 会丢行），一并清掉。
    if product_ids:
        session.execute(delete(Transaction).where(Transaction.product_id.in_(product_ids)))
    session.execute(delete(Transfer).where(Transfer.transfer_no.like(f"{_FLOW_PREFIX}%")))
    session.execute(delete(Deposit).where(Deposit.deposit_no.like(f"{_FLOW_PREFIX}%")))
    session.execute(delete(RiskRuleChange).where(RiskRuleChange.rule_id.in_(rule_ids)))
    session.execute(delete(RiskRule).where(RiskRule.id.in_(rule_ids)))
    session.execute(
        delete(SuitabilityDecision).where(
            or_(
                SuitabilityDecision.assessment_id.in_(assessment_ids),
                SuitabilityDecision.customer_id.in_(demo_customer_ids),
            )
        )
    )
    session.execute(delete(RiskAssessment).where(RiskAssessment.id.in_(assessment_ids)))
    session.execute(delete(FundingAccount).where(FundingAccount.customer_id.in_(demo_customer_ids)))
    session.execute(delete(CustomerProfile).where(CustomerProfile.customer_id.in_(demo_customer_ids)))
    session.execute(delete(Customer).where(Customer.id.in_(demo_customer_ids)))
    session.execute(delete(Product).where(Product.id.in_(product_ids)))
    session.flush()


# ---------------------------------------------------------------- 客户与风评


def _seed_customers(session: Session, context: _Context, password_hash: str) -> None:
    managers = [context["employees"][_MANAGER_ONE], context["employees"][_MANAGER_TWO]]
    for index in range(1, DEMO_CUSTOMERS + 1):
        level = _LEVELS[(index - 1) % len(_LEVELS)]
        manager = managers[(index - 1) % 2]
        surname = _SURNAMES[(index - 1) % len(_SURNAMES)]
        given = _GIVEN_NAMES[((index - 1) // len(_SURNAMES)) % len(_GIVEN_NAMES)]
        customer = Customer(
            username=f"{_USERNAME_PREFIX}{index:03d}",
            password_hash=password_hash,
            real_name=f"{surname}{given}",
            id_number=f"9001011991{index:08d}",
            phone=f"139{index:08d}",
            customer_level=level,
            status="正常",
            manager_id=manager.id,
            opened_at=datetime(2023, 1, 1, 9, 0, 0) + timedelta(days=(index - 1) * 21),
        )
        session.add(customer)
        session.flush()
        session.add(
            CustomerProfile(
                customer_id=customer.id,
                risk_level=_LEVEL_RISK[level],
                risk_score=_SCORE_BY_LEVEL[_LEVEL_RISK[level]],
                investment_experience=_LEVEL_EXPERIENCE[level],
                annual_income_range=_LEVEL_INCOME[level],
                total_assets=_LEVEL_TOTAL_ASSETS[level],
                target_allocation=_LEVEL_TARGET[level],
                product_preference=_LEVEL_PREFERENCE[level],
                confidence_score=Decimal("0.80"),
                computed_at=customer.opened_at + timedelta(days=15),
            )
        )
        session.add(
            FundingAccount(customer_id=customer.id, available_balance=_LEVEL_BALANCE[level])
        )
    session.flush()


def _seed_assessments(session: Session, context: _Context) -> None:
    """每位演示客户 25 条风评记录：24 条历史（已过期）+ 1 条有效期内的。

    等级一律取该客户画像上的等级，因此补进来的那条不会改变他的当前等级，只是把
    「有效期」续上——在此之前 lisic2/zhangc3/zhaoc4 的测评早已过期，产品筛选会直接
    403，分页根本走不到。
    """
    customers = [context["customers"][DEMO_CUSTOMER_USERNAME], *context["demo_customers"]]
    profiles = {
        row.customer_id: row
        for row in session.scalars(
            select(CustomerProfile).where(
                CustomerProfile.customer_id.in_([row.id for row in customers])
            )
        ).all()
    }
    for customer in customers:
        profile = profiles.get(customer.id)
        risk_level = profile.risk_level if profile is not None else "C1"
        score = _SCORE_BY_LEVEL[risk_level]
        answers = [{"q": question, "a": "A", "score": score} for question in (1, 5, 9, 16)]
        for index, day in enumerate(_HISTORICAL_ASSESSMENT_DATES):
            session.add(
                RiskAssessment(
                    customer_id=customer.id,
                    assessment_date=day,
                    total_score=score,
                    risk_level=risk_level,
                    answers=answers,
                    assessor_type="客户自测" if index % 2 else "人工评估",
                    valid_until=day + timedelta(days=365),
                )
            )
        session.add(
            RiskAssessment(
                customer_id=customer.id,
                assessment_date=_CURRENT_ASSESSMENT_DATE,
                total_score=score,
                risk_level=risk_level,
                answers=answers,
                assessor_type="客户自测",
                valid_until=_CURRENT_ASSESSMENT_VALID_UNTIL,
            )
        )
    session.flush()


# ---------------------------------------------------------------- 产品


def _seed_products(session: Session, context: _Context) -> None:
    """50 只在售产品：R1/R2/R3 各 14 只（C3 客户看到 45 只 → 3 页），R4/R5 各 4 只。

    R1 到 R3 是刻意压重的：客户侧的演示账号 zhangc3 是 C3，只能看到这三档；R4/R5 留给
    产品筛选页的等级筛选（也留给 C4/C5 的客户）。
    """
    codes_by_risk: dict[str, int] = {"R1": 14, "R2": 14, "R3": 14, "R4": 4, "R5": 4}
    manager_names = ("吴宁", "郑岚", "冯川", "曹越", "蒋远", "邵行")
    index = 1
    for risk_level, count in codes_by_risk.items():
        tier = int(risk_level[1:])
        for slot in range(count):
            product_type = _PRODUCT_TYPE_BY_RISK[risk_level]
            session.add(
                Product(
                    product_code=f"{_PRODUCT_PREFIX}{index:06d}",
                    product_name=f"演示{tier}号{product_type}·{slot + 1}期",
                    product_type=product_type,
                    risk_level=risk_level,
                    expected_return=Decimal(str(1.5 + tier * 2.2 + slot * 0.1)).quantize(
                        Decimal("0.0001")
                    ),
                    min_amount=Decimal(str(1000 * (1 + slot % 3))),
                    term_days=0 if product_type == "货币基金" else 90 * (1 + slot % 4),
                    fund_manager=manager_names[(index - 1) % len(manager_names)],
                    fee_rate=Decimal(str(0.2 + tier * 0.25)).quantize(Decimal("0.0001")),
                    nav=Decimal(str(1.0 + tier * 0.5 + slot * 0.01)).quantize(Decimal("0.000001")),
                    status="在售",
                )
            )
            index += 1
    session.flush()


# ---------------------------------------------------------------- 交易流水


def _seed_flow_records(session: Session, context: _Context) -> None:
    """zhangc3 名下 103 笔流水：申购/转账/充值各 26 笔、赎回 25 笔。

    每一类占一个日期带（各自 25 笔、逐日推进），因此「按类型筛」与「按日期段筛」各自
    都能筛出两页；末尾另有三笔落在同一秒的记录，用来验证排序兜底键在翻页时稳定。
    """
    customer = context["customers"][DEMO_CUSTOMER_USERNAME]
    product = context["products"].get(_FLOW_PRODUCT_CODE)
    if product is None:
        raise RuntimeError(f"基础种子缺产品 {_FLOW_PRODUCT_CODE}")
    nav = Decimal("1.500000")

    for index in range(FLOW_PER_TYPE):
        amount = Decimal(str(10000 + index * 2500))
        fee = (amount * Decimal("0.012")).quantize(Decimal("0.01"))
        session.add(
            Transaction(
                transaction_no=f"{_FLOW_PREFIX}TX{index:05d}",
                customer_id=customer.id,
                product_id=product.id,
                transaction_type="申购",
                amount=amount,
                shares=(amount / nav).quantize(Decimal("0.0001")),
                nav=nav,
                fee=fee,
                status="已确认",
                create_time=_PURCHASE_BASE + timedelta(days=index, minutes=index),
            )
        )

        redeem_amount = Decimal(str(5000 + index * 1500))
        redeem_fee = (redeem_amount * Decimal("0.005")).quantize(Decimal("0.01"))
        redeem_shares = ((redeem_amount + redeem_fee) / nav).quantize(Decimal("0.0001"))
        session.add(
            Transaction(
                transaction_no=f"{_FLOW_PREFIX}RX{index:05d}",
                customer_id=customer.id,
                product_id=product.id,
                transaction_type="赎回",
                amount=redeem_amount,
                shares=redeem_shares,
                nav=nav,
                fee=redeem_fee,
                status="已确认",
                create_time=_REDEEM_BASE + timedelta(days=index, minutes=index),
            )
        )

        session.add(
            Transfer(
                transfer_no=f"{_FLOW_PREFIX}TR{index:05d}",
                customer_id=customer.id,
                amount=Decimal(str(8000 + index * 1200)),
                payee_name="王五",
                payee_account="6222020200998877665",
                create_time=_TRANSFER_BASE + timedelta(days=index, minutes=index),
            )
        )

        session.add(
            Deposit(
                deposit_no=f"{_FLOW_PREFIX}DP{index:05d}",
                customer_id=customer.id,
                amount=Decimal(str(20000 + index * 3000)),
                create_time=_DEPOSIT_BASE + timedelta(days=index, minutes=index),
            )
        )

    # 同一秒的三笔：跨三张表，靠来源序号兜底成固定顺序。
    session.add(
        Transaction(
            transaction_no=f"{_FLOW_PREFIX}TX{FLOW_PER_TYPE:05d}",
            customer_id=customer.id,
            product_id=product.id,
            transaction_type="申购",
            amount=Decimal("66666.00"),
            shares=Decimal("44444.0000"),
            nav=nav,
            fee=Decimal("799.99"),
            status="已确认",
            create_time=_SAME_SECOND,
        )
    )
    session.add(
        Transfer(
            transfer_no=f"{_FLOW_PREFIX}TR{FLOW_PER_TYPE:05d}",
            customer_id=customer.id,
            amount=Decimal("12345.00"),
            payee_name="李四",
            payee_account="6222020200998877666",
            create_time=_SAME_SECOND,
        )
    )
    session.add(
        Deposit(
            deposit_no=f"{_FLOW_PREFIX}DP{FLOW_PER_TYPE:05d}",
            customer_id=customer.id,
            amount=Decimal("54321.00"),
            create_time=_SAME_SECOND,
        )
    )
    session.flush()


# ---------------------------------------------------------------- 预警与风险关注


def _rule_hit(spec: Any, observed: str) -> dict[str, Any]:
    field = FIELD_REGISTRY[spec.field]
    operator = OPERATOR_REGISTRY[spec.operator]
    threshold = spec.threshold
    if "value" in threshold:
        threshold_text = str(threshold["value"])
    else:
        threshold_text = f"{threshold.get('min', '')}~{threshold.get('max', '')}"
    return {
        "rule_code": spec.rule_code,
        "rule_name": spec.rule_name,
        "category": spec.category,
        "alert_level": spec.alert_level,
        "weight": float(spec.weight),
        "field": spec.field,
        "field_label": field.label,
        "operator": spec.operator,
        "operator_label": operator.label,
        "operator_symbol": operator.symbol,
        "threshold": threshold_text,
        "observed_value": observed,
        "evidence": f"{field.label} {observed} {operator.symbol} 阈值 {threshold_text}",
    }


def _demoted_spec(index: int) -> Any:
    return RISK_RULE_SEEDS[index % len(RISK_RULE_SEEDS)]


def _seed_alerts_and_focus(session: Session, context: _Context) -> None:
    now = context["now"]
    customers = [context["customers"][DEMO_CUSTOMER_USERNAME], *context["demo_customers"]]
    risk_officer = context["employees"][_RISK_OFFICER]
    levels = ("轻度", "中度", "重度")
    statuses = ("未处理", "未处理", "未处理", "已排除", "已升级")
    observed_values = ("168000.00", "520000.00", "96000.00", "3", "12", "0.8", "36")

    for index in range(ALERTS):
        customer = customers[index % len(customers)]
        specs = [_demoted_spec(index), _demoted_spec(index + 7)]
        if index % 3 == 0:
            specs.append(_demoted_spec(index + 13))
        hits = [_rule_hit(spec, observed_values[(index + slot) % len(observed_values)]) for slot, spec in enumerate(specs)]
        status = statuses[index % len(statuses)]
        create_time = now - timedelta(hours=6 * index + index % 5)
        session.add(
            RiskAlert(
                customer_id=customer.id,
                alert_type=hits[0]["category"],
                alert_level=levels[index % len(levels)],
                confidence=Decimal(str(0.55 + (index % 9) * 0.05)),
                rule_codes=[hit["rule_code"] for hit in hits],
                rule_hits=hits,
                trigger_detail=MARK
                + "\n"
                + "\n".join(f"{hit['rule_name']}（{hit['rule_code']}）：{hit['evidence']}" for hit in hits),
                transaction_ids=[],
                status=status,
                handler_id=risk_officer.id if status != "未处理" else None,
                handle_result=("已联系客户核实资金来源" if status == "已排除" else "已升级为重度预警并派生工单")
                if status != "未处理"
                else None,
                create_time=create_time,
                update_time=create_time,
            )
        )

    focus_types = ("风控预警", "风控预警", "高风险意图")
    for index in range(FOCUS_RECORDS):
        customer = customers[(index * 3) % len(customers)]
        focus_type = focus_types[index % len(focus_types)]
        occurred_at = now - timedelta(hours=4 * index + index % 3)
        if focus_type == "风控预警":
            level = levels[index % len(levels)]
            reason = f"{MARK}风控预警（{level}）：命中规则 {_demoted_spec(index).rule_code}"
            severity: str | None = level
            source = "risk-monitoring-agent"
        else:
            reason = f"{MARK}客服识别到高风险意图：客户询问规避大额申报的转账拆分方式"
            severity = None
            source = "customer-service-agent"
        session.add(
            RiskFocus(
                customer_id=customer.id,
                focus_type=focus_type,
                severity=severity,
                reason=reason,
                source=source,
                trace_id=f"{_THREAD_PREFIX}trace-{index:04d}",
                occurred_at=occurred_at,
            )
        )
    session.flush()


def _seed_disabled_rules(session: Session) -> None:
    """12 条**停用**的规则：规则列表不按 `enabled` 过滤，停用的照样在列表里，
    但匹配链路只读启用的（`enabled_rule_specs`），于是列表够翻页而风控行为不变。

    字段与算子只从既有 20 条规则里挑现成的组合，落到 CHECK 白名单内——序列化会拿
    `field`/`operator` 查注册表，写错一个值就是 500 而不是一条不命中的规则。
    """
    combinations = (
        ("amount", "gte", {"value": "300000"}, 24),
        ("amount", "gte", {"value": "800000"}, 72, "重度"),
        ("purchase_amount", "window_sum_gte", {"value": "800000"}, 168),
        ("redeem_amount", "gte", {"value": "300000"}, None, "重度"),
        ("amount", "daily_count_gte", {"value": "8"}, None),
        ("amount", "window_count_gte", {"value": "15"}, 168, "重度"),
        ("hour_of_day", "outside", {"min": "7", "max": "21"}, None),
        ("amount_to_assets_ratio", "gte", {"value": "60"}, None),
        ("reverse_interval_hours", "lte", {"value": "6"}, None, "重度"),
        ("threshold_avoidance_amount", "window_count_gte", {"value": "4"}, 24, "重度"),
        ("small_amount", "window_count_gte", {"value": "30"}, 168),
        ("product_id", "window_distinct_count_gte", {"value": "6"}, 24),
    )
    for index, item in enumerate(combinations, start=1):
        field, operator, threshold, window_hours = item[0], item[1], item[2], item[3]
        alert_level = item[4] if len(item) > 4 else "中度"
        spec = next(
            (row for row in RISK_RULE_SEEDS if row.field == field and row.operator == operator),
            RISK_RULE_SEEDS[0],
        )
        session.add(
            RiskRule(
                rule_code=f"{_RULE_PREFIX}{index:02d}",
                rule_name=f"演示备选规则{index:02d}·{spec.category}",
                category=spec.category,
                description=f"演示用的备选口径（当前停用，不参与匹配）：在「{spec.rule_name}」的基础上收紧阈值。",
                field=field,
                operator=operator,
                threshold=threshold,
                window_hours=window_hours,
                alert_level=alert_level,
                weight=Decimal("1.50"),
                enabled=False,
            )
        )
    session.flush()


# ---------------------------------------------------------------- 工单


def _seed_work_orders(session: Session, context: _Context) -> None:
    now = context["now"]
    risk_officer = context["employees"][_RISK_OFFICER]
    advisor = context["employees"][_ADVISOR]
    customers = [context["customers"][DEMO_CUSTOMER_USERNAME], *context["demo_customers"]]
    alert_ids = list(
        session.scalars(
            select(RiskAlert.id)
            .where(RiskAlert.trigger_detail.like(f"{MARK}%"))
            .order_by(RiskAlert.id.asc())
            .limit(10)
        ).all()
    )
    # 四个状态的下标区间：前 10 张由演示预警派生（来源预警编号可筛），其余来自客户投诉
    # 与转人工——与受理侧「预警之外的来源只支持这两种」一致。
    plan = (
        [("预警处置", "特急", "已完成")] * 4
        + [("预警处置", "紧急", "处理中")] * 3
        + [("预警处置", "普通", "待处理")] * 3
        + [("客户投诉", "紧急", "已完成")] * 8
        + [("客户投诉", "普通", "已关闭")] * 4
        + [("客户投诉", "普通", "处理中")] * 4
        + [("转人工", "普通", "待处理")] * 6
        + [("转人工", "紧急", "已完成")] * 4
        + [("转人工", "普通", "处理中")] * 3
        + [("转人工", "普通", "已关闭")] * 5
    )
    for index, (order_type, priority, status) in enumerate(plan, start=1):
        customer = customers[(index * 5) % len(customers)]
        handler = risk_officer if index % 4 else advisor
        create_time = now - timedelta(hours=9 * index + index % 7)
        source_alert_id = alert_ids[index - 1] if index <= len(alert_ids) else None
        order = WorkOrder(
            work_order_no=f"{_ORDER_PREFIX}{index:04d}",
            order_type=order_type,
            sub_type=None,
            source_alert_id=source_alert_id,
            customer_id=customer.id,
            submitter_identity="internal",
            submitter_id=risk_officer.id,
            handler_id=handler.id,
            current_node=status,
            priority=priority,
            status=status,
            biz_content={"主题": _WORK_ORDER_THEMES[(index - 1) % len(_WORK_ORDER_THEMES)]},
            handle_reason="已受理并联系客户核实" if status != "待处理" else None,
            handle_result="客户已确认知悉，事项办结" if status == "已完成" else None,
            create_time=create_time,
            update_time=create_time,
        )
        session.add(order)
        session.flush()

        # 建单也记一条流转（`from_status` 为空）：每个状态都有出处，详情页一次看全。
        transitions = [(None, "待处理", create_time)]
        if status in ("处理中", "已完成", "已关闭"):
            transitions.append(("待处理", "处理中", create_time + timedelta(hours=2)))
        if status in ("已完成", "已关闭"):
            transitions.append(("处理中", status, create_time + timedelta(hours=6)))
        for from_status, to_status, handled_at in transitions:
            session.add(
                WorkOrderTransition(
                    work_order_id=order.id,
                    from_status=from_status,
                    to_status=to_status,
                    handler_id=handler.id,
                    reason="建单受理" if from_status is None else f"流转至{to_status}",
                    handled_at=handled_at,
                )
            )
    session.flush()


# ---------------------------------------------------------------- 投顾内容


def _candidates(
    context: _Context, allowed_levels: tuple[str, ...], limit: int = 3
) -> list[dict[str, Any]]:
    rows = [
        product
        for product in context["products"].values()
        if product.risk_level in allowed_levels and product.status == "在售"
    ]
    rows.sort(key=lambda row: row.product_code)
    result: list[dict[str, Any]] = []
    for slot, product in enumerate(rows[:limit]):
        score = round(0.95 - slot * 0.12, 4)
        result.append(
            {
                "product_code": product.product_code,
                "product_name": product.product_name,
                "product_type": product.product_type,
                "risk_level": product.risk_level,
                "expected_return": format(product.expected_return, "f"),
                "term_days": product.term_days,
                "composite_score": score,
                "score_breakdown": [
                    {
                        "dimension": "收益",
                        "raw_value": f"{format(product.expected_return, 'f')}%",
                        "score": score,
                        "weight": 0.4,
                        "contribution": round(score * 0.4, 4),
                    },
                    {
                        "dimension": "风险",
                        "raw_value": product.risk_level,
                        "score": score,
                        "weight": 0.3,
                        "contribution": round(score * 0.3, 4),
                    },
                    {
                        "dimension": "期限匹配度",
                        "raw_value": f"{product.term_days}天",
                        "score": score,
                        "weight": 0.3,
                        "contribution": round(score * 0.3, 4),
                    },
                ],
                "reason": f"客户风险承受等级与产品风险等级 {product.risk_level} 匹配；"
                f"预期年化收益 {format(product.expected_return, 'f')}%；"
                f"期限 {product.term_days} 天，与目标配置的持有周期相称。",
            }
        )
    return result


def _pool_snapshot(context: _Context, allowed_levels: tuple[str, ...]) -> dict[str, Any]:
    rows = [
        product
        for product in context["products"].values()
        if product.risk_level in allowed_levels and product.status == "在售"
    ]
    rows.sort(key=lambda row: row.product_code)
    return {
        "products": [
            {
                "product_code": row.product_code,
                "product_name": row.product_name,
                "product_type": row.product_type,
                "risk_level": row.risk_level,
            }
            for row in rows
        ],
        "allowed_product_risk_levels": list(allowed_levels),
    }


def _allowed_levels(risk_level: str) -> tuple[str, ...]:
    top = int(risk_level[1:])
    return tuple(f"R{index}" for index in range(1, top + 1))


def _seed_advisory(session: Session, context: _Context) -> None:
    """投顾内容：45 份已放行定稿（客户「我的方案」+ 顾问审核历史）、20 条待审方案、
    12 条待审操作建议、12 条已驳回方案、45 条方案请求。

    **待审内容不是生成流程跑出来的**，运行时里没有中断点，点「放行」会被拒（见模块
    说明）；这里的用途是把「队列 / 历史 / 请求」三段列表撑到多页，并让筛选与排序有内容。
    """
    now = context["now"]
    advisor = context["employees"][_ADVISOR]
    manager_one = context["employees"][_MANAGER_ONE]
    manager_two = context["employees"][_MANAGER_TWO]
    demo_customer = context["customers"][DEMO_CUSTOMER_USERNAME]
    demo_customers = context["demo_customers"]
    other_customers = [demo_customer, *demo_customers]

    profiles = {
        row.customer_id: row
        for row in session.scalars(
            select(CustomerProfile).where(
                CustomerProfile.customer_id.in_([row.id for row in other_customers])
            )
        ).all()
    }

    def add_plan(
        customer: Customer,
        *,
        index: int,
        status: str,
        moment: datetime,
        advisor_id: int,
        reason: str | None = None,
    ) -> None:
        profile = profiles.get(customer.id)
        risk_level = profile.risk_level if profile is not None else "C3"
        allowed = _allowed_levels(risk_level)
        candidates = _candidates(context, allowed)
        allocation = dict(profile.target_allocation) if profile is not None else {"股票": 30, "债券": 40, "现金": 20, "另类": 10}
        draft = AdvisoryDraft(
            customer_id=customer.id,
            advisor_id=advisor_id,
            tilt=_PLAN_TILTS[index % len(_PLAN_TILTS)],
            content_classification="投顾内容",
            candidates=candidates,
            allocation_suggestion=allocation,
            warnings=[],
            profile_computed_at=profile.computed_at if profile is not None else moment,
            candidate_pool_snapshot=_pool_snapshot(context, allowed),
            generated_at=moment,
        )
        session.add(draft)
        session.flush()
        review = AdvisoryReview(
            content_type="方案",
            content_ref=draft.id,
            draft_id=draft.id,
            thread_id=f"{_THREAD_PREFIX}plan-{index:04d}",
            status=status,
            create_time=moment,
            update_time=moment,
        )
        session.add(review)
        session.flush()
        if status == "已放行":
            session.add(
                AdvisoryReviewAudit(
                    review_id=review.id,
                    advisor_id=advisor_id,
                    action="放行",
                    reason=None,
                    decided_at=moment,
                )
            )
            session.add(
                AdvisoryFinal(
                    draft_id=draft.id,
                    customer_id=customer.id,
                    advisor_id=advisor_id,
                    content_classification="投顾内容",
                    candidates=candidates,
                    allocation_suggestion=allocation,
                    warnings=[],
                    released_at=moment,
                )
            )
        elif status == "已驳回":
            session.add(
                AdvisoryReviewAudit(
                    review_id=review.id,
                    advisor_id=advisor_id,
                    action="驳回",
                    reason=reason or "候选池与客户目标配置偏离较大，请重新生成。",
                    decided_at=moment,
                )
            )

    # 45 份已放行：全部挂在 zhangc3 名下（客户「我的方案」3 页），同一位顾问放行，
    # 于是顾问的审核历史也够 3 页。
    for index in range(RELEASED_PLANS):
        moment = now - timedelta(hours=6 * index + index % 4)
        add_plan(demo_customer, index=index, status="已放行", moment=moment, advisor_id=advisor.id)

    # 12 条已驳回：只进审核历史（统计两类动作都翻得到）。
    for index in range(REJECTED_PLANS):
        customer = other_customers[(index * 7) % len(other_customers)]
        moment = now - timedelta(hours=8 * index + 5)
        add_plan(
            customer,
            index=RELEASED_PLANS + index,
            status="已驳回",
            moment=moment,
            advisor_id=advisor.id,
        )

    # 20 条待审（含 4 条「处理中」）：队列按等待时长升序，先用先审。
    for index in range(PENDING_PLANS):
        customer = other_customers[(index * 11) % len(other_customers)]
        moment = now - timedelta(hours=12 * index + 2)
        add_plan(
            customer,
            index=RELEASED_PLANS + REJECTED_PLANS + index,
            status="处理中" if index % 5 == 0 else "待审",
            moment=moment,
            advisor_id=advisor.id,
        )

    # 12 条待审操作建议：与方案合并在同一条队列里（两类内容共用队列）。
    for index in range(PENDING_ADVICES):
        customer = other_customers[(index * 13) % len(other_customers)]
        moment = now - timedelta(hours=14 * index + 3)
        product = context["products"].get(_FLOW_PRODUCT_CODE)
        direction = "申购" if index % 2 == 0 else "赎回"
        amount = Decimal(str(20000 + index * 5000))
        draft = OperationAdviceDraft(
            customer_id=customer.id,
            manager_id=(manager_one if index % 2 else manager_two).id,
            product_code=product.product_code if product is not None else "F000001",
            direction=direction,
            amount=amount,
            redeemed_shares=None
            if direction == "申购"
            else (amount / Decimal("1.5")).quantize(Decimal("0.0001")),
            reason=_ADVICE_REASONS[index % len(_ADVICE_REASONS)],
            content_classification="投顾内容",
            generated_at=moment,
        )
        session.add(draft)
        session.flush()
        session.add(
            AdvisoryReview(
                content_type="操作建议",
                content_ref=draft.id,
                draft_id=None,
                thread_id=f"{_THREAD_PREFIX}advice-{index:04d}",
                status="处理中" if index % 6 == 0 else "待审",
                create_time=moment,
                update_time=moment,
            )
        )

    # 45 条方案请求：24 条挂 zhangc3（客户「我的方案」的请求区 2 页），其余分散。
    for index in range(ADVISORY_REQUESTS):
        customer = demo_customer if index < ADVISORY_REQUESTS - 21 else other_customers[index % len(other_customers)]
        submitted_at = now - timedelta(hours=10 * index + 1)
        session.add(
            AdvisoryRequest(
                request_no=f"{_REQUEST_PREFIX}{index:04d}",
                customer_id=customer.id,
                status="待处理",
                filters={"product_type": "混合基金", "risk_level": "R3"},
                condition_fingerprint=f"{_THREAD_PREFIX}fp-{index:04d}",
                submitted_at=submitted_at,
            )
        )
    session.flush()


def _seed_operation_advice(session: Session, context: _Context) -> None:
    """zhangc3 名下 52 条已送达的操作建议：四个客户侧状态齐全。

    状态是**算出来**的（`status_of`）：26 条落在 7 天有效期内且没有决定（待客户决定，
    按状态筛选也是 2 页）、10 条有「接受」决定、8 条有「拒绝」决定、8 条送达超过
    7 个自然日（已过期）。
    """
    now = context["now"]
    customer = context["customers"][DEMO_CUSTOMER_USERNAME]
    advisor = context["employees"][_ADVISOR]
    manager = context["employees"][_MANAGER_ONE]
    product = context["products"].get(_FLOW_PRODUCT_CODE)

    # (方向, 送达距今天数, 决定) —— 前 26 条留在有效期内且无决定。
    plan: list[tuple[str, int, str | None]] = []
    for index in range(26):
        plan.append(("申购" if index % 2 == 0 else "赎回", 0, None))
    for index in range(10):
        plan.append(("申购" if index % 2 == 0 else "赎回", index % 7, "接受"))
    for index in range(8):
        plan.append(("申购" if index % 2 == 0 else "赎回", index % 7, "拒绝"))
    for index in range(8):
        plan.append(("申购" if index % 2 == 0 else "赎回", 8 + index, None))

    for index, (direction, days_ago, decision) in enumerate(plan):
        if decision is None and days_ago >= 7:
            released_at = now - timedelta(days=days_ago, hours=index % 5)
        elif decision is None:
            # 待客户决定：送达必须落在 7 个自然日以内，且各自错开，翻页顺序看得出来。
            released_at = now - timedelta(hours=(index + 1) * 6 + index % 3)
        else:
            released_at = now - timedelta(days=days_ago, hours=index % 5 + 1)
        amount = Decimal(str(15000 + index * 2200))
        draft = OperationAdviceDraft(
            customer_id=customer.id,
            manager_id=manager.id,
            product_code=product.product_code if product is not None else "F000003",
            direction=direction,
            amount=amount,
            redeemed_shares=None
            if direction == "申购"
            else (amount / Decimal("1.5")).quantize(Decimal("0.0001")),
            reason=_ADVICE_REASONS[index % len(_ADVICE_REASONS)],
            content_classification="投顾内容",
            generated_at=released_at - timedelta(minutes=30),
        )
        session.add(draft)
        session.flush()
        review = AdvisoryReview(
            content_type="操作建议",
            content_ref=draft.id,
            draft_id=None,
            thread_id=f"{_THREAD_PREFIX}delivered-{index:04d}",
            status="已放行",
            create_time=released_at,
            update_time=released_at,
        )
        session.add(review)
        session.flush()
        session.add(
            AdvisoryReviewAudit(
                review_id=review.id,
                advisor_id=advisor.id,
                action="放行",
                reason=None,
                decided_at=released_at,
            )
        )
        if decision is not None:
            session.add(
                OperationAdviceDecision(
                    advice_id=draft.id,
                    customer_id=customer.id,
                    decision=decision,
                    decided_at=released_at + timedelta(hours=3),
                )
            )
    session.flush()


# ---------------------------------------------------------------- 会话 / 分析 / 知识


def _seed_conversations(session: Session, context: _Context) -> None:
    now = context["now"]
    customer = context["customers"][DEMO_CUSTOMER_USERNAME]
    for index in range(CUSTOMER_SESSIONS):
        question, answer = _CHAT_PAIRS[index % len(_CHAT_PAIRS)]
        session_id = f"{_SESSION_PREFIX}{index:04d}"
        started_at = now - timedelta(hours=5 * index + index % 4)
        session.add(
            ConversationArchive(
                session_id=session_id,
                identity_domain="customer",
                user_id=customer.id,
                agent_type="customer-service",
                role="user",
                content=question,
                tool_calls=None,
                citations=None,
                content_classification=None,
                create_time=started_at,
            )
        )
        session.add(
            ConversationArchive(
                session_id=session_id,
                identity_domain="customer",
                user_id=customer.id,
                agent_type="customer-service",
                role="assistant",
                content=answer,
                tool_calls=None,
                citations=None,
                content_classification="事实性内容",
                create_time=started_at + timedelta(seconds=20),
            )
        )
    session.flush()


def _seed_analytics_history(session: Session, context: _Context) -> None:
    """每位内部员工 45 条查询留痕——分析历史按提问人过滤，只能看到自己名下的。"""
    now = context["now"]
    statuses = ("成功", "成功", "成功", "超出可查范围", "校验拒绝")
    employees = [
        context["employees"][_ADVISOR],
        context["employees"][_MANAGER_ONE],
        context["employees"][_MANAGER_TWO],
        context["employees"][_RISK_OFFICER],
    ]
    for employee in employees:
        for index in range(ANALYTICS_PER_EMPLOYEE):
            question = _ANALYTICS_QUESTIONS[index % len(_ANALYTICS_QUESTIONS)]
            status = statuses[index % len(statuses)]
            succeeded = status == "成功"
            session.add(
                AnalyticsQueryAudit(
                    employee_id=employee.id,
                    question=question,
                    generated_sql=(
                        "SELECT risk_level, COUNT(*) AS product_count FROM va_product_element "
                        "WHERE product_status = '在售' GROUP BY risk_level ORDER BY risk_level"
                        if succeeded
                        else None
                    ),
                    status=status,
                    row_count=5 if succeeded else None,
                    truncated=False,
                    error_code=None if succeeded else 1004,
                    create_time=now - timedelta(hours=3 * index + employee.id),
                )
            )
    session.flush()


def _seed_knowledge_documents(session: Session) -> None:
    """40 篇文档：30 已入库 + 6 处理中 + 4 处理失败。

    状态与知识类型都必须落在接口的枚举内（`FAQ/产品/政策`、`processing/active/failed/
    expired`）——数据库没有 CHECK 拦着，但序列化会把它 cast 进 `Literal`，写错就是 500。
    文档列表默认排掉「已过期」，因此列表默认看到 36 篇（2 页）。
    """
    types = ("FAQ", "产品", "政策")
    for index in range(KNOWLEDGE_DOCUMENTS):
        knowledge_type = types[index % len(types)]
        if index >= KNOWLEDGE_DOCUMENTS - 10:
            position = index - (KNOWLEDGE_DOCUMENTS - 10)
            if position < 6:
                status = "processing"
                stage: str | None = ("parse", "chunk", "embed", "store")[position % 4]
                failure_reason = None
                chunk_count = 0
            else:
                status = "failed"
                stage = None
                failure_reason = "文档解析失败：文件编码无法识别"
                chunk_count = 0
        else:
            status = "active"
            stage = None
            failure_reason = None
            chunk_count = 8 + index % 12
        session.add(
            KnowledgeMeta(
                knowledge_type=knowledge_type,
                title=f"{_DOC_TITLES[index % len(_DOC_TITLES)]}（演示{index + 1:02d}）",
                source_file=f"{_DOC_PREFIX}policy_{index + 1:02d}.md",
                minio_path=None,
                milvus_collection=None,
                version="v1",
                status=status,
                stage=stage,
                failure_reason=failure_reason,
                chunk_count=chunk_count,
                expire_at=None,
            )
        )
    session.flush()


# ---------------------------------------------------------------- 汇报


def _report() -> None:
    print("分页演示数据已就绪（重新执行等于恢复成这一版）：")
    print(f"  演示客户 {DEMO_CUSTOMERS} 位、演示产品 {DEMO_PRODUCTS} 只、"
          f"演示规则 {DISABLED_RULES} 条（停用）")
    print(f"  zhangc3 名下：交易流水 {FLOW_PER_TYPE * 4 + 3} 笔、操作建议 {CUSTOMER_ADVICES} 条、"
          f"已放行方案 {RELEASED_PLANS} 份、历史会话 {CUSTOMER_SESSIONS} 场")
    print(f"  zhangc3 的风评记录：{len(_ASSESSMENT_DATES)} 条（含 1 条有效期至 "
          f"{_CURRENT_ASSESSMENT_VALID_UNTIL.isoformat()}）")
    print(f"  内部侧：预警 {ALERTS} 条、风险关注 {FOCUS_RECORDS} 条、工单 {WORK_ORDERS} 张、"
          f"知识文档 {KNOWLEDGE_DOCUMENTS} 篇、分析历史 {ANALYTICS_PER_EMPLOYEE} 条/人")
    print(f"  投顾：待审 {PENDING_PLANS + PENDING_ADVICES} 条、已驳回 {REJECTED_PLANS} 条、"
          f"方案请求 {ADVISORY_REQUESTS} 条")
    print(f"  完成时间：{datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    if "--purge" in sys.argv[1:]:
        purge_pagination_demo()
        print("已清掉分页演示数据。")
    else:
        seed_pagination_demo()
