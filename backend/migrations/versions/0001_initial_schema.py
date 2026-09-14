"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-09-14

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOW = sa.text("CURRENT_TIMESTAMP")


def upgrade() -> None:
    op.create_table(
        "conversation_archive",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False, comment="会话标识"),
        sa.Column("identity_domain", sa.String(length=16), nullable=False, comment="身份域"),
        sa.Column("user_id", sa.BigInteger(), nullable=False, comment="使用者标识"),
        sa.Column("agent_type", sa.String(length=32), nullable=False, comment="Agent"),
        sa.Column("role", sa.String(length=16), nullable=False, comment="消息角色"),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False, comment="对话内容"),
        sa.Column("tool_calls", sa.JSON(), nullable=True, comment="工具调用记录"),
        sa.Column("citations", sa.JSON(), nullable=True, comment="引用文档"),
        sa.Column(
            "content_classification",
            sa.String(length=32),
            nullable=True,
            comment="内容分类",
        ),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="会话归档",
    )
    op.create_index(
        "ix_conversation_archive_session_id",
        "conversation_archive",
        ["session_id"],
        unique=False,
    )
    op.create_table(
        "fin_knowledge_meta",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("knowledge_type", sa.String(length=32), nullable=False, comment="知识类型"),
        sa.Column("title", sa.String(length=255), nullable=False, comment="标题"),
        sa.Column("source_file", sa.String(length=255), nullable=False, comment="来源文件"),
        sa.Column("minio_path", sa.String(length=512), nullable=True, comment="对象存储路径"),
        sa.Column(
            "milvus_collection", sa.String(length=128), nullable=True, comment="向量集合名"
        ),
        sa.Column("version", sa.String(length=32), nullable=False, comment="版本"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="状态"),
        sa.Column("chunk_count", sa.Integer(), nullable=False, comment="分块数"),
        sa.Column("expire_at", sa.DateTime(), nullable=True, comment="过期时间"),
        sa.Column(
            "create_time",
            sa.DateTime(),
            server_default=_NOW,
            nullable=False,
            comment="入库时间",
        ),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="知识元数据",
    )
    op.create_table(
        "fin_product",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_code", sa.String(length=32), nullable=False, comment="产品代码"),
        sa.Column("product_name", sa.String(length=128), nullable=False, comment="产品名称"),
        sa.Column("product_type", sa.String(length=32), nullable=False, comment="产品类型"),
        sa.Column("risk_level", sa.String(length=8), nullable=False, comment="产品风险等级"),
        sa.Column(
            "expected_return",
            sa.Numeric(precision=7, scale=4),
            nullable=False,
            comment="预期年化收益率",
        ),
        sa.Column(
            "min_amount", sa.Numeric(precision=16, scale=2), nullable=False, comment="起投金额"
        ),
        sa.Column("term_days", sa.Integer(), nullable=False, comment="期限天数"),
        sa.Column("fund_manager", sa.String(length=64), nullable=True, comment="基金经理"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="产品状态"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_code"),
        sa.CheckConstraint(
            "risk_level IN ('R1','R2','R3','R4','R5')",
            name="ck_product_risk_level",
        ),
        comment="产品",
    )
    op.create_table(
        "sys_customer",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False, comment="登录账号"),
        sa.Column("password_hash", sa.String(length=255), nullable=False, comment="密码散列"),
        sa.Column("real_name", sa.String(length=64), nullable=False, comment="真实姓名"),
        sa.Column("id_number", sa.String(length=18), nullable=False, comment="身份证号"),
        sa.Column("phone", sa.String(length=11), nullable=False, comment="手机号"),
        sa.Column("customer_level", sa.String(length=16), nullable=False, comment="客户分层"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="账号状态"),
        sa.Column("opened_at", sa.DateTime(), nullable=False, comment="开户时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id_number"),
        sa.UniqueConstraint("username"),
        comment="客户",
    )
    op.create_table(
        "sys_employee",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False, comment="登录账号"),
        sa.Column("password_hash", sa.String(length=255), nullable=False, comment="密码散列"),
        sa.Column("real_name", sa.String(length=64), nullable=False, comment="真实姓名"),
        sa.Column("employee_role", sa.String(length=32), nullable=False, comment="员工角色"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="账号状态"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        comment="员工",
    )
    op.create_table(
        "biz_work_order",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("work_order_no", sa.String(length=64), nullable=False, comment="工单编号"),
        sa.Column("order_type", sa.String(length=32), nullable=False, comment="工单类型"),
        sa.Column("sub_type", sa.String(length=32), nullable=True, comment="子类型"),
        sa.Column("customer_id", sa.BigInteger(), nullable=True, comment="关联客户"),
        sa.Column("submitter_identity", sa.String(length=16), nullable=False, comment="提交人身份域"),
        sa.Column("submitter_id", sa.BigInteger(), nullable=False, comment="提交人标识"),
        sa.Column("handler_id", sa.BigInteger(), nullable=True, comment="受理人"),
        sa.Column("current_node", sa.String(length=32), nullable=False, comment="当前节点"),
        sa.Column("priority", sa.String(length=8), nullable=False, comment="优先级"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="工单状态"),
        sa.Column("biz_content", sa.JSON(), nullable=True, comment="业务内容"),
        sa.Column("handle_reason", sa.Text(), nullable=True, comment="最近一次流转理由"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.ForeignKeyConstraint(["handler_id"], ["sys_employee.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_order_no"),
        comment="工单",
    )
    op.create_table(
        "fin_customer_profile",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("risk_level", sa.String(length=8), nullable=False, comment="风险承受等级"),
        sa.Column("risk_score", sa.Integer(), nullable=False, comment="风险评分"),
        sa.Column("investment_experience", sa.String(length=16), nullable=False, comment="投资经验"),
        sa.Column("annual_income_range", sa.String(length=32), nullable=False, comment="年收入区间"),
        sa.Column(
            "total_assets", sa.Numeric(precision=18, scale=2), nullable=False, comment="总资产"
        ),
        sa.Column("target_allocation", sa.JSON(), nullable=False, comment="目标配置"),
        sa.Column("product_preference", sa.JSON(), nullable=False, comment="产品偏好"),
        sa.Column(
            "confidence_score",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            comment="画像置信度",
        ),
        sa.Column("computed_at", sa.DateTime(), nullable=False, comment="画像计算时间"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id"),
        sa.CheckConstraint(
            "risk_level IN ('C1','C2','C3','C4','C5')",
            name="ck_profile_risk_level",
        ),
        comment="客户画像",
    )
    op.create_table(
        "fin_holdings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("product_id", sa.BigInteger(), nullable=False, comment="产品标识"),
        sa.Column("shares", sa.Numeric(precision=18, scale=4), nullable=False, comment="持有份额"),
        sa.Column(
            "cost_amount", sa.Numeric(precision=18, scale=2), nullable=False, comment="成本金额"
        ),
        sa.Column(
            "current_value", sa.Numeric(precision=18, scale=2), nullable=False, comment="当前市值"
        ),
        sa.Column(
            "profit_loss", sa.Numeric(precision=18, scale=2), nullable=False, comment="盈亏金额"
        ),
        sa.Column(
            "profit_ratio", sa.Numeric(precision=8, scale=4), nullable=False, comment="盈亏比例"
        ),
        sa.Column("status", sa.String(length=16), nullable=False, comment="持仓状态"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["fin_product.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", "product_id", name="uk_holdings_customer_product"),
        comment="持仓",
    )
    op.create_table(
        "fin_risk_alert",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("alert_type", sa.String(length=32), nullable=False, comment="预警类型"),
        sa.Column("alert_level", sa.String(length=8), nullable=False, comment="预警级别"),
        sa.Column("trigger_detail", sa.Text(), nullable=False, comment="触发详情"),
        sa.Column("transaction_ids", sa.JSON(), nullable=True, comment="关联交易标识"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="预警状态"),
        sa.Column("handler_id", sa.BigInteger(), nullable=True, comment="处置人"),
        sa.Column("handle_result", sa.Text(), nullable=True, comment="处置结论"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.Column("update_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.ForeignKeyConstraint(["handler_id"], ["sys_employee.id"]),
        sa.PrimaryKeyConstraint("id"),
        comment="预警",
    )
    op.create_table(
        "fin_risk_assessment",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("assessment_date", sa.Date(), nullable=False, comment="评估日期"),
        sa.Column("total_score", sa.Integer(), nullable=False, comment="总分"),
        sa.Column("risk_level", sa.String(length=8), nullable=False, comment="风险承受等级"),
        sa.Column("answers", sa.JSON(), nullable=False, comment="答题详情"),
        sa.Column("assessor_type", sa.String(length=16), nullable=False, comment="评估方式"),
        sa.Column("valid_until", sa.Date(), nullable=False, comment="有效期至"),
        sa.Column("create_time", sa.DateTime(), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "risk_level IN ('C1','C2','C3','C4','C5')",
            name="ck_assessment_risk_level",
        ),
        comment="风险评估记录",
    )
    op.create_index(
        "ix_fin_risk_assessment_customer_id",
        "fin_risk_assessment",
        ["customer_id"],
        unique=False,
    )
    op.create_table(
        "fin_transaction",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("transaction_no", sa.String(length=64), nullable=False, comment="交易流水号"),
        sa.Column("customer_id", sa.BigInteger(), nullable=False, comment="客户标识"),
        sa.Column("product_id", sa.BigInteger(), nullable=False, comment="产品标识"),
        sa.Column("transaction_type", sa.String(length=16), nullable=False, comment="交易类型"),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False, comment="交易金额"),
        sa.Column("shares", sa.Numeric(precision=18, scale=4), nullable=False, comment="成交份额"),
        sa.Column("nav", sa.Numeric(precision=12, scale=6), nullable=False, comment="成交净值"),
        sa.Column("fee", sa.Numeric(precision=12, scale=2), nullable=False, comment="手续费"),
        sa.Column("status", sa.String(length=16), nullable=False, comment="交易状态"),
        sa.Column("operator_id", sa.BigInteger(), nullable=True, comment="经办员工标识"),
        sa.Column("create_time", sa.DateTime(), nullable=False, comment="成交时间"),
        sa.ForeignKeyConstraint(["customer_id"], ["sys_customer.id"]),
        sa.ForeignKeyConstraint(["operator_id"], ["sys_employee.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["fin_product.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_no"),
        comment="交易流水",
    )
    op.create_index(
        "ix_fin_transaction_customer_id",
        "fin_transaction",
        ["customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("fin_transaction")
    op.drop_table("fin_risk_assessment")
    op.drop_table("fin_risk_alert")
    op.drop_table("fin_holdings")
    op.drop_table("fin_customer_profile")
    op.drop_table("biz_work_order")
    op.drop_table("sys_employee")
    op.drop_table("sys_customer")
    op.drop_table("fin_product")
    op.drop_table("fin_knowledge_meta")
    op.drop_table("conversation_archive")
