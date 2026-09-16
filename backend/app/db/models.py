from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Customer(Base):
    __tablename__ = "sys_customer"
    __table_args__ = {"comment": "客户"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, comment="登录账号")
    password_hash: Mapped[str] = mapped_column(String(255), comment="密码散列")
    real_name: Mapped[str] = mapped_column(String(64), comment="真实姓名")
    id_number: Mapped[str] = mapped_column(String(18), unique=True, comment="身份证号")
    phone: Mapped[str] = mapped_column(String(11), comment="手机号")
    customer_level: Mapped[str] = mapped_column(String(16), comment="客户分层")
    status: Mapped[str] = mapped_column(String(16), comment="账号状态")
    manager_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_employee.id"),
        index=True,
        comment="客户关系归属人（客户经理）",
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime, comment="开户时间")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Employee(Base):
    __tablename__ = "sys_employee"
    __table_args__ = {"comment": "员工"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, comment="登录账号")
    password_hash: Mapped[str] = mapped_column(String(255), comment="密码散列")
    real_name: Mapped[str] = mapped_column(String(64), comment="真实姓名")
    employee_role: Mapped[str] = mapped_column(String(32), comment="员工角色")
    status: Mapped[str] = mapped_column(String(16), comment="账号状态")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class CustomerProfile(Base):
    __tablename__ = "fin_customer_profile"
    __table_args__ = (
        CheckConstraint(
            "risk_level IN ('C1','C2','C3','C4','C5')",
            name="ck_profile_risk_level",
        ),
        {"comment": "客户画像"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sys_customer.id"),
        unique=True,
        comment="客户标识",
    )
    risk_level: Mapped[str] = mapped_column(String(8), comment="风险承受等级")
    risk_score: Mapped[int] = mapped_column(comment="风险评分")
    investment_experience: Mapped[str] = mapped_column(String(16), comment="投资经验")
    annual_income_range: Mapped[str] = mapped_column(String(32), comment="年收入区间")
    total_assets: Mapped[Decimal] = mapped_column(Numeric(18, 2), comment="总资产")
    target_allocation: Mapped[dict] = mapped_column(JSON, comment="目标配置")
    product_preference: Mapped[dict] = mapped_column(JSON, comment="产品偏好")
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), comment="画像置信度")
    computed_at: Mapped[datetime] = mapped_column(DateTime, comment="画像计算时间")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ProfileTag(Base):
    __tablename__ = "fin_profile_tag"
    __table_args__ = (
        UniqueConstraint("customer_id", "tag_key", name="uk_profile_tag_customer_key"),
        {"comment": "客户画像标签"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), comment="客户标识"
    )
    tag_key: Mapped[str] = mapped_column(String(32), comment="标签键")
    tag_value: Mapped[object] = mapped_column(JSON, comment="标签值")
    source: Mapped[str] = mapped_column(String(32), comment="来源")
    evidence_count: Mapped[int] = mapped_column(comment="证据条数")
    observed_at: Mapped[datetime] = mapped_column(DateTime, comment="写入时间")
    reason: Mapped[str | None] = mapped_column(Text, comment="修正理由")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ProfileTagConflict(Base):
    __tablename__ = "fin_profile_tag_conflict"
    __table_args__ = (
        Index("ix_profile_tag_conflict_customer_key", "customer_id", "tag_key"),
        {"comment": "客户画像标签冲突记录"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), comment="客户标识"
    )
    tag_key: Mapped[str] = mapped_column(String(32), comment="标签键")
    old_value: Mapped[object] = mapped_column(JSON, comment="旧值")
    old_source: Mapped[str] = mapped_column(String(32), comment="旧来源")
    new_value: Mapped[object] = mapped_column(JSON, comment="新值")
    new_source: Mapped[str] = mapped_column(String(32), comment="新来源")
    changed_at: Mapped[datetime] = mapped_column(DateTime, comment="覆盖时间")
    reason: Mapped[str | None] = mapped_column(Text, comment="修正理由")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Product(Base):
    __tablename__ = "fin_product"
    __table_args__ = (
        CheckConstraint(
            "risk_level IN ('R1','R2','R3','R4','R5')",
            name="ck_product_risk_level",
        ),
        {"comment": "产品"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(String(32), unique=True, comment="产品代码")
    product_name: Mapped[str] = mapped_column(String(128), comment="产品名称")
    product_type: Mapped[str] = mapped_column(String(32), comment="产品类型")
    risk_level: Mapped[str] = mapped_column(String(8), comment="产品风险等级")
    expected_return: Mapped[Decimal] = mapped_column(Numeric(7, 4), comment="预期年化收益率")
    min_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2), comment="起投金额")
    term_days: Mapped[int] = mapped_column(comment="期限天数")
    fund_manager: Mapped[str | None] = mapped_column(String(64), comment="基金经理")
    fee_rate: Mapped[Decimal] = mapped_column(Numeric(7, 4), comment="费率")
    status: Mapped[str] = mapped_column(String(16), comment="产品状态")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class UnderlyingAsset(Base):
    __tablename__ = "fin_underlying_asset"
    __table_args__ = (
        CheckConstraint(
            "asset_category IN ('现金','债券','股票','另类')",
            name="ck_underlying_asset_category",
        ),
        {"comment": "底层资产"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    asset_code: Mapped[str] = mapped_column(String(32), unique=True, comment="底层资产代码")
    asset_name: Mapped[str] = mapped_column(String(128), comment="底层资产名称")
    asset_category: Mapped[str] = mapped_column(String(32), comment="资产大类")
    industry: Mapped[str] = mapped_column(String(32), comment="所属行业")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ProductUnderlying(Base):
    """产品底层持有关系：一条记录指向一个底层资产，而底层资产可以是另一个产品的份额。"""

    __tablename__ = "fin_product_underlying"
    __table_args__ = (
        UniqueConstraint("product_id", "child_product_id", name="uk_product_underlying_child"),
        UniqueConstraint(
            "product_id", "underlying_asset_id", name="uk_product_underlying_asset"
        ),
        CheckConstraint(
            "(child_product_id IS NOT NULL AND underlying_asset_id IS NULL)"
            " OR (child_product_id IS NULL AND underlying_asset_id IS NOT NULL)",
            name="ck_product_underlying_single_target",
        ),
        CheckConstraint("weight > 0", name="ck_product_underlying_weight"),
        {"comment": "产品底层持有关系"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fin_product.id"), comment="产品标识"
    )
    child_product_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fin_product.id"), comment="作为底层资产的产品标识"
    )
    underlying_asset_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fin_underlying_asset.id"), comment="底层资产标识"
    )
    weight: Mapped[Decimal] = mapped_column(Numeric(9, 6), comment="占该产品的比例")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class Transaction(Base):
    __tablename__ = "fin_transaction"
    __table_args__ = (
        Index("ix_fin_transaction_customer_id", "customer_id"),
        {"comment": "交易流水"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    transaction_no: Mapped[str] = mapped_column(String(64), unique=True, comment="交易流水号")
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), comment="客户标识"
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fin_product.id"), comment="产品标识"
    )
    transaction_type: Mapped[str] = mapped_column(String(16), comment="交易类型")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), comment="交易金额")
    shares: Mapped[Decimal] = mapped_column(Numeric(18, 4), comment="成交份额")
    nav: Mapped[Decimal] = mapped_column(Numeric(12, 6), comment="成交净值")
    fee: Mapped[Decimal] = mapped_column(Numeric(12, 2), comment="手续费")
    status: Mapped[str] = mapped_column(String(16), comment="交易状态")
    operator_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_employee.id"), comment="经办员工标识"
    )
    create_time: Mapped[datetime] = mapped_column(DateTime, comment="成交时间")


class Holding(Base):
    __tablename__ = "fin_holdings"
    __table_args__ = (
        UniqueConstraint("customer_id", "product_id", name="uk_holdings_customer_product"),
        {"comment": "持仓"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), comment="客户标识"
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fin_product.id"), comment="产品标识"
    )
    shares: Mapped[Decimal] = mapped_column(Numeric(18, 4), comment="持有份额")
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), comment="成本金额")
    current_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), comment="当前市值")
    profit_loss: Mapped[Decimal] = mapped_column(Numeric(18, 2), comment="盈亏金额")
    profit_ratio: Mapped[Decimal] = mapped_column(Numeric(8, 4), comment="盈亏比例")
    status: Mapped[str] = mapped_column(String(16), comment="持仓状态")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class RiskAssessment(Base):
    __tablename__ = "fin_risk_assessment"
    __table_args__ = (
        CheckConstraint(
            "risk_level IN ('C1','C2','C3','C4','C5')",
            name="ck_assessment_risk_level",
        ),
        {"comment": "风险评估记录"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), index=True, comment="客户标识"
    )
    assessment_date: Mapped[date] = mapped_column(Date, comment="评估日期")
    total_score: Mapped[int] = mapped_column(comment="总分")
    risk_level: Mapped[str] = mapped_column(String(8), comment="风险承受等级")
    answers: Mapped[list] = mapped_column(JSON, comment="答题详情")
    assessor_type: Mapped[str] = mapped_column(String(16), comment="评估方式")
    valid_until: Mapped[date] = mapped_column(Date, comment="有效期至")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SuitabilityDecision(Base):
    __tablename__ = "fin_suitability_decision"
    __table_args__ = (
        Index("ix_suitability_decision_customer_id", "customer_id"),
        CheckConstraint(
            "customer_risk_level IN ('C1','C2','C3','C4','C5')",
            name="ck_suitability_customer_risk_level",
        ),
        {"comment": "适当性判定记录"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), comment="客户标识"
    )
    assessment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fin_risk_assessment.id"), comment="依据的评测"
    )
    customer_risk_level: Mapped[str] = mapped_column(String(8), comment="判定时的风险承受等级")
    allowed_product_risk_levels: Mapped[list] = mapped_column(JSON, comment="允许的产品风险等级")
    decided_at: Mapped[datetime] = mapped_column(DateTime, comment="判定时间")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RiskAlert(Base):
    __tablename__ = "fin_risk_alert"
    __table_args__ = {"comment": "预警"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), comment="客户标识"
    )
    alert_type: Mapped[str] = mapped_column(String(32), comment="预警类型")
    alert_level: Mapped[str] = mapped_column(String(8), comment="预警级别")
    trigger_detail: Mapped[str] = mapped_column(Text, comment="触发详情")
    transaction_ids: Mapped[list | None] = mapped_column(JSON, comment="关联交易标识")
    status: Mapped[str] = mapped_column(String(16), comment="预警状态")
    handler_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_employee.id"), comment="处置人"
    )
    handle_result: Mapped[str | None] = mapped_column(Text, comment="处置结论")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class WorkOrder(Base):
    __tablename__ = "biz_work_order"
    __table_args__ = {"comment": "工单"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    work_order_no: Mapped[str] = mapped_column(String(64), unique=True, comment="工单编号")
    order_type: Mapped[str] = mapped_column(String(32), comment="工单类型")
    sub_type: Mapped[str | None] = mapped_column(String(32), comment="子类型")
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), comment="关联客户"
    )
    submitter_identity: Mapped[str] = mapped_column(String(16), comment="提交人身份域")
    submitter_id: Mapped[int] = mapped_column(BigInteger, comment="提交人标识")
    handler_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sys_employee.id"), comment="受理人"
    )
    current_node: Mapped[str] = mapped_column(String(32), comment="当前节点")
    priority: Mapped[str] = mapped_column(String(8), comment="优先级")
    status: Mapped[str] = mapped_column(String(16), comment="工单状态")
    biz_content: Mapped[dict | None] = mapped_column(JSON, comment="业务内容")
    handle_reason: Mapped[str | None] = mapped_column(Text, comment="最近一次流转理由")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AdvisoryRequest(Base):
    __tablename__ = "biz_advisory_request"
    __table_args__ = (
        Index("ix_advisory_request_customer_fingerprint", "customer_id", "condition_fingerprint"),
        CheckConstraint(
            "status IN ('待处理','处理中','已完成','已关闭')",
            name="ck_advisory_request_status",
        ),
        {"comment": "方案请求"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    request_no: Mapped[str] = mapped_column(String(32), unique=True, comment="请求编号")
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), comment="客户标识"
    )
    status: Mapped[str] = mapped_column(String(16), comment="请求状态")
    filters: Mapped[dict] = mapped_column(JSON, comment="触发它的筛选条件")
    condition_fingerprint: Mapped[str] = mapped_column(String(64), comment="筛选条件指纹")
    submitted_at: Mapped[datetime] = mapped_column(DateTime, comment="提交时间")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AdvisoryDraft(Base):
    """AI 原稿；没有 update_time 是刻意的，见 app.advisory.draft。"""

    __tablename__ = "biz_advisory_draft"
    __table_args__ = (
        Index("ix_advisory_draft_customer_id", "customer_id"),
        CheckConstraint(
            "content_classification IN ('投顾内容','事实性内容')",
            name="ck_advisory_draft_content_classification",
        ),
        {"comment": "AI 原稿"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), comment="客户标识"
    )
    advisor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_employee.id"), comment="发起生成的理财顾问"
    )
    tilt: Mapped[str] = mapped_column(String(16), comment="生成时指定的侧重")
    content_classification: Mapped[str] = mapped_column(String(32), comment="内容分类")
    candidates: Mapped[list] = mapped_column(JSON, comment="排序后的候选产品与推荐理由")
    allocation_suggestion: Mapped[dict] = mapped_column(JSON, comment="资产配置比例建议")
    warnings: Mapped[list] = mapped_column(JSON, comment="画像警示")
    profile_computed_at: Mapped[datetime] = mapped_column(
        DateTime, comment="生成时使用的画像版本（画像计算时间）"
    )
    candidate_pool_snapshot: Mapped[dict] = mapped_column(JSON, comment="生成时的候选池快照")
    generated_at: Mapped[datetime] = mapped_column(DateTime, comment="生成时间")
    advisory_request_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("biz_advisory_request.id"),
        comment="触发本次生成的客户方案请求（顾问自行发起时为空）",
    )
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AdvisoryReview(Base):
    """AI 原稿的审核状态与并发锁；同一份原稿最多一条审核记录。

    `thread_id` 是生成流程在 LangGraph 运行时上的线程标识——放行或驳回时
    靠它找到那次运行、把它从中断处恢复（ADR-0007），不是自己维护的状态机。
    """

    __tablename__ = "biz_advisory_review"
    __table_args__ = (
        CheckConstraint(
            "status IN ('待审','处理中','已放行','已驳回')",
            name="ck_advisory_review_status",
        ),
        {"comment": "投顾内容审核状态"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("biz_advisory_draft.id"), unique=True, comment="对应的 AI 原稿"
    )
    thread_id: Mapped[str] = mapped_column(
        String(64), unique=True, comment="生成流程在运行时上的线程标识"
    )
    status: Mapped[str] = mapped_column(String(16), comment="审核状态")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AdvisoryReviewAudit(Base):
    __tablename__ = "biz_advisory_review_audit"
    __table_args__ = (
        Index("ix_advisory_review_audit_review_id", "review_id"),
        CheckConstraint(
            "action IN ('放行','驳回')",
            name="ck_advisory_review_audit_action",
        ),
        {"comment": "审核操作留痕"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("biz_advisory_review.id"), comment="对应的审核记录"
    )
    advisor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_employee.id"), comment="审核人"
    )
    action: Mapped[str] = mapped_column(String(8), comment="操作")
    reason: Mapped[str | None] = mapped_column(Text, comment="驳回理由")
    decided_at: Mapped[datetime] = mapped_column(DateTime, comment="操作时间")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AdvisoryReviewComment(Base):
    """审核页上的留言；不是审核决定，仅供客户经理与理财顾问沟通用，见 app.advisory.comments。"""

    __tablename__ = "biz_advisory_review_comment"
    __table_args__ = (
        Index("ix_advisory_review_comment_review_id", "review_id"),
        {"comment": "审核留言"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    review_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("biz_advisory_review.id"), comment="对应的审核记录"
    )
    author_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_employee.id"), comment="留言人"
    )
    author_role: Mapped[str] = mapped_column(String(32), comment="留言人角色")
    body: Mapped[str] = mapped_column(Text, comment="留言内容")
    created_at: Mapped[datetime] = mapped_column(DateTime, comment="留言时间")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AdvisoryFinal(Base):
    """顾问定稿；唯一允许送达客户的版本，落库后不可修改。

    与 AI 原稿并存，两者的差异是举证「审核是实质性的」的依据，见
    app.advisory.draft。
    """

    __tablename__ = "biz_advisory_final"
    __table_args__ = (
        Index("ix_advisory_final_customer_id", "customer_id"),
        CheckConstraint(
            "content_classification IN ('投顾内容','事实性内容')",
            name="ck_advisory_final_content_classification",
        ),
        {"comment": "顾问定稿"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    draft_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("biz_advisory_draft.id"), unique=True, comment="对应的 AI 原稿"
    )
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), comment="客户标识"
    )
    advisor_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_employee.id"), comment="放行的理财顾问"
    )
    content_classification: Mapped[str] = mapped_column(String(32), comment="内容分类")
    candidates: Mapped[list] = mapped_column(JSON, comment="顾问确认后的推荐产品与理由")
    allocation_suggestion: Mapped[dict] = mapped_column(JSON, comment="顾问确认后的配置建议")
    warnings: Mapped[list] = mapped_column(JSON, comment="顾问确认后的画像警示")
    released_at: Mapped[datetime] = mapped_column(DateTime, comment="放行时间")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class ConversationArchive(Base):
    __tablename__ = "conversation_archive"
    __table_args__ = (
        Index("ix_conversation_archive_session_id", "session_id"),
        {"comment": "会话归档"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), comment="会话标识")
    identity_domain: Mapped[str] = mapped_column(String(16), comment="身份域")
    user_id: Mapped[int] = mapped_column(BigInteger, comment="使用者标识")
    agent_type: Mapped[str] = mapped_column(String(32), comment="Agent")
    role: Mapped[str] = mapped_column(String(16), comment="消息角色")
    content: Mapped[str] = mapped_column(MEDIUMTEXT, comment="对话内容")
    tool_calls: Mapped[list | None] = mapped_column(JSON, comment="工具调用记录")
    citations: Mapped[list | None] = mapped_column(JSON, comment="引用文档")
    content_classification: Mapped[str | None] = mapped_column(String(32), comment="内容分类")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AnalyticsQueryAudit(Base):
    __tablename__ = "biz_analytics_query_audit"
    __table_args__ = (
        Index("ix_analytics_query_audit_employee_id", "employee_id"),
        CheckConstraint(
            "status IN ('成功','超出可查范围','生成失败','校验拒绝','查询超时','执行失败')",
            name="ck_analytics_query_audit_status",
        ),
        {"comment": "数据分析查询留痕"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_employee.id"), comment="提问人"
    )
    question: Mapped[str] = mapped_column(Text, comment="自然语言问题")
    generated_sql: Mapped[str | None] = mapped_column(Text, comment="生成的查询")
    status: Mapped[str] = mapped_column(String(16), comment="结果状态")
    row_count: Mapped[int | None] = mapped_column(comment="返回行数")
    truncated: Mapped[bool] = mapped_column(default=False, comment="是否被截断")
    error_code: Mapped[int | None] = mapped_column(comment="业务错误码")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class KnowledgeMeta(Base):
    __tablename__ = "fin_knowledge_meta"
    __table_args__ = {"comment": "知识元数据"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    knowledge_type: Mapped[str] = mapped_column(String(32), comment="知识类型")
    title: Mapped[str] = mapped_column(String(255), comment="标题")
    source_file: Mapped[str] = mapped_column(String(255), comment="来源文件")
    minio_path: Mapped[str | None] = mapped_column(String(512), comment="对象存储路径")
    milvus_collection: Mapped[str | None] = mapped_column(String(128), comment="向量集合名")
    version: Mapped[str] = mapped_column(String(32), comment="版本")
    status: Mapped[str] = mapped_column(String(16), comment="状态")
    stage: Mapped[str | None] = mapped_column(String(16), comment="处理阶段")
    failure_reason: Mapped[str | None] = mapped_column(Text, comment="失败原因")
    chunk_count: Mapped[int] = mapped_column(default=0, comment="分块数")
    expire_at: Mapped[datetime | None] = mapped_column(DateTime, comment="过期时间")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), comment="入库时间")
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
