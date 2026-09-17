from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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


class RiskRule(Base):
    """风控规则：存储在库中的声明式条件，由代码中封闭的算子求值。

    可配的只有五个部分：取哪个 `field`、用哪个 `operator` 比、阈值多少、时间窗
    多长、命中算什么等级。没有「并且」「或者」，也拼不出表达式——能表达的只有
    `app.risk_monitoring.operators` 里那几种形状。新增一种判定方式必须改代码并出
    迁移，下面三条 CHECK 守的是同一份清单。

    `alert_level` 是规则自身的预警等级，不是「命中这条规则就一定产生该等级预警」
    ——预警的等级由命中条数与该客户的历史预警记录推导。
    """

    __tablename__ = "fin_risk_rule"
    __table_args__ = (
        CheckConstraint(
            "alert_level IN ('轻度','中度','重度')",
            name="ck_risk_rule_alert_level",
        ),
        CheckConstraint(
            "operator IN ("
            "'gt','gte','lt','lte','eq','ne','between','outside',"
            "'window_count_gte','window_sum_gte','window_max_gte',"
            "'window_distinct_count_gte','daily_count_gte','daily_sum_gte')",
            name="ck_risk_rule_operator",
        ),
        CheckConstraint(
            "window_hours IS NOT NULL OR operator NOT IN "
            "('window_count_gte','window_sum_gte','window_max_gte',"
            "'window_distinct_count_gte')",
            name="ck_risk_rule_window_hours",
        ),
        CheckConstraint(
            "field IN ("
            "'amount','purchase_amount','redeem_amount','hour_of_day',"
            "'amount_to_assets_ratio','risk_level_gap','reverse_interval_hours',"
            "'threshold_avoidance_amount','small_amount','large_round_amount',"
            "'product_id')",
            name="ck_risk_rule_field",
        ),
        {"comment": "风控规则"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_code: Mapped[str] = mapped_column(String(16), unique=True, comment="规则编号")
    rule_name: Mapped[str] = mapped_column(String(128), comment="规则名称")
    category: Mapped[str] = mapped_column(String(32), comment="规则分类")
    description: Mapped[str] = mapped_column(Text, comment="触发条件描述")
    field: Mapped[str] = mapped_column(String(32), comment="被判定的字段")
    operator: Mapped[str] = mapped_column(String(32), comment="运算符")
    threshold: Mapped[dict] = mapped_column(JSON, comment="阈值")
    window_hours: Mapped[int | None] = mapped_column(
        comment="时间窗长度（小时），仅时间窗算子使用"
    )
    alert_level: Mapped[str] = mapped_column(String(8), comment="预警等级")
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 2), comment="规则权重")
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, comment="是否启用；停用后不参与匹配"
    )
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class RiskRuleChange(Base):
    """风控规则的调整记录：谁在什么时候把什么改成了什么，理由是什么。

    阈值是监管口径的落点，口径一变就得跟着变，所以「变了」本身必须可追溯——只看
    到现在的阈值，看不出它是初始口径还是上周被谁调过。启停同样记一笔。
    """

    __tablename__ = "fin_risk_rule_change"
    __table_args__ = (
        Index("ix_risk_rule_change_rule_id", "rule_id"),
        CheckConstraint(
            "change_type IN ('阈值调整','启停变更')",
            name="ck_risk_rule_change_type",
        ),
        {"comment": "风控规则调整记录"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    rule_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("fin_risk_rule.id"), comment="规则标识"
    )
    change_type: Mapped[str] = mapped_column(String(16), comment="调整类型")
    old_value: Mapped[dict] = mapped_column(JSON, comment="调整前的配置项")
    new_value: Mapped[dict] = mapped_column(JSON, comment="调整后的配置项")
    # 这里叫 changed_by 而不是 operator_id：规则表上已经有一个「运算符」叫 operator，
    # 同词异义比多一个字母难读得多。
    changed_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_employee.id"), comment="调整人"
    )
    reason: Mapped[str] = mapped_column(Text, comment="调整理由")
    changed_at: Mapped[datetime] = mapped_column(DateTime, comment="调整时间")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RiskAlert(Base):
    """预警：规则命中后产生的、带等级与置信度的事实记录（CONTEXT「预警」）。

    它承载的全部内容是「什么规则在什么交易上命中了」：命中的规则编号、关联交易、
    关联客户、等级、置信度、可展示到字段与值粒度的触发详情。

    `status` / `handler_id` / `handle_result` 是预警**自身**的处置留痕（未处理 →
    已排除 / 已升级），由处置链路写入，不从预警派生工单那一刻起就替工单干活。
    工单有自己的受理人、节点与流转理由，两套生命周期不合并——把工单的状态字段
    搬进预警表会让「预警是什么」变得含糊。
    """

    __tablename__ = "fin_risk_alert"
    __table_args__ = {"comment": "预警"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_customer.id"), comment="客户标识"
    )
    alert_type: Mapped[str] = mapped_column(String(32), comment="预警类型")
    alert_level: Mapped[str] = mapped_column(String(8), comment="预警级别")
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), comment="置信度；仅用于排序与分级展示"
    )
    rule_codes: Mapped[list] = mapped_column(JSON, comment="命中的规则编号")
    # 命中依据的结构化快照（字段、实测值、阈值）。它是**命中那一刻**的口径：阈值可以
    # 被调整，展示时回查规则会把今天的口径套到过去的预警上，而风控专员正是靠这个
    # 判断误报。形状与 `app.risk_monitoring.context.RuleHit` 一一对应，
    # `trigger_detail` 是同一份事实的文本呈现。
    rule_hits: Mapped[list] = mapped_column(
        JSON, comment="命中规则的依据快照：字段、实测值、阈值"
    )
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
    """工单：处置某一事项的流程载体（CONTEXT「工单」）。

    生命周期是 `待处理 → 处理中 → 已完成 | 已关闭`，`current_node` 与 `status`
    同步推进——这里没有并行分支，一个字段就是当前状态。

    `source_alert_id` 是唯一约束：**一条预警最多派生一张工单**。预警之外的来源
    （客户投诉、转人工）留空，而 MySQL 的唯一索引允许多个 NULL，所以这类工单
    不受限制。

    `handler_id` 是受理人（建单时即确定的责任人），`handle_result` 是处置结论。
    「谁在什么时候因为什么把工单推到了哪个状态」不在这一行上，而在只追加的
    `biz_work_order_transition` 里——行只保留最近一次的理由。
    """

    __tablename__ = "biz_work_order"
    __table_args__ = (
        UniqueConstraint("source_alert_id", name="uk_work_order_source_alert"),
        {"comment": "工单"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    work_order_no: Mapped[str] = mapped_column(String(64), unique=True, comment="工单编号")
    order_type: Mapped[str] = mapped_column(String(32), comment="工单类型")
    sub_type: Mapped[str | None] = mapped_column(String(32), comment="子类型")
    source_alert_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("fin_risk_alert.id"),
        comment="来源预警标识；一条预警最多派生一张工单",
    )
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
    handle_result: Mapped[str | None] = mapped_column(Text, comment="处置结论")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class WorkOrderTransition(Base):
    """工单状态流转留痕：每一次流转的处置人、时间与非空理由。

    与 `biz_advisory_review_audit` 同一形状：当前状态留在工单那一行，而「谁把它
    推到了这个状态」留在这张只追加的表里。**建单也记一条**（`from_status` 为空），
    于是工单的每一个状态都有出处，不存在凭空出现的状态。

    `reason` 非空由数据库与代码两侧共同保证：理由为空的流转请求在服务层就被拒绝，
    即使绕过服务层也写不进这一列。
    """

    __tablename__ = "biz_work_order_transition"
    __table_args__ = (
        Index("ix_work_order_transition_work_order_id", "work_order_id"),
        CheckConstraint(
            "to_status IN ('待处理','处理中','已完成','已关闭')",
            name="ck_work_order_transition_to_status",
        ),
        {"comment": "工单状态流转留痕"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("biz_work_order.id"), comment="对应的工单"
    )
    from_status: Mapped[str | None] = mapped_column(
        String(16), comment="流转前状态；建单时为空"
    )
    to_status: Mapped[str] = mapped_column(String(16), comment="流转后状态")
    handler_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("sys_employee.id"), comment="处置人"
    )
    reason: Mapped[str] = mapped_column(Text, comment="流转理由")
    handled_at: Mapped[datetime] = mapped_column(DateTime, comment="处置时间")
    create_time: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


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


class GraphSyncRun(Base):
    """知识图谱全量重建记录。

    `lock_key` 进行中时固定取值，结束（成功或失败）后置空——靠它在 `UNIQUE`
    约束上做并发互斥，同一时刻只能有一条记录持有这个值，见 app.knowledge_graph.service。
    """

    __tablename__ = "biz_graph_sync_run"
    __table_args__ = (
        UniqueConstraint("lock_key", name="uk_graph_sync_run_lock"),
        CheckConstraint(
            "status IN ('进行中','成功','失败')",
            name="ck_graph_sync_run_status",
        ),
        {"comment": "知识图谱全量重建记录"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    lock_key: Mapped[str | None] = mapped_column(
        String(16), comment="进行中时固定取值用于并发互斥，结束后置空"
    )
    status: Mapped[str] = mapped_column(String(16), comment="重建状态")
    node_count: Mapped[int | None] = mapped_column(comment="节点数")
    relationship_count: Mapped[int | None] = mapped_column(comment="关系数")
    started_at: Mapped[datetime] = mapped_column(DateTime, comment="触发时间")
    duration_ms: Mapped[int | None] = mapped_column(comment="耗时（毫秒）")
    failure_reason: Mapped[str | None] = mapped_column(Text, comment="失败原因")
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
