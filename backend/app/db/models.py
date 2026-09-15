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
    status: Mapped[str] = mapped_column(String(16), comment="产品状态")
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
