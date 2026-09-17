"""开户：客户经理为客户建立账户与初始画像。

客户与内部员工分属两个身份域（ADR-0004），客户账号不能自助注册——账户由其
归属的客户经理开立（业务规则：客户关系的归属人负责建立这层关系）。开户时
采集的自述信息（收入、资产、投资经验、目标配置）成为初始画像，来源标为
「默认值」：它们是待确认的自述，不是研判结论。此后风评问卷、持仓与交易行为
按各自的来源等级改写画像。

初始画像必须在这里建出来：风险评测的提交、适当性的判定都以画像存在为前提。
新客户的账户里没有一张画像行，旅程在第一步就走不下去——这个缺口在端到端
串起来时才暴露（ticket 07），由开户补上。
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import redis
from argon2 import PasswordHasher
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.customer_profile.confidence import (
    SOURCE_DEFAULT,
    SOURCE_INITIAL_CONFIDENCE,
)
from app.customer_profile.judgement import EXPERIENCE_SCORES, INCOME_SCORES
from app.customer_profile.service import write_tag
from app.db.models import Customer, CustomerProfile, Employee
from app.exceptions import AppError

USERNAME_TAKEN_MESSAGE = "登录账号已被使用"
ID_NUMBER_TAKEN_MESSAGE = "证件号已开户"
INVALID_LEVEL_MESSAGE = "未知的客户分层"
INVALID_INCOME_MESSAGE = "未知的收入区间"
INVALID_EXPERIENCE_MESSAGE = "未知的投资经验"
INVALID_ASSETS_MESSAGE = "资产规模必须是不为负的数字"
INVALID_PHONE_MESSAGE = "手机号应为 11 位数字"
INVALID_ID_NUMBER_MESSAGE = "证件号应为 18 位"
INVALID_PASSWORD_MESSAGE = "初始密码至少 8 位"
INVALID_USERNAME_MESSAGE = "登录账号不能为空"

CUSTOMER_LEVELS = ("普通", "金卡", "白金", "钻石", "私行")
_PHONE_PATTERN = re.compile(r"^\d{11}$")


def open_account(
    db: Session,
    cache: redis.Redis,
    *,
    username: str,
    password: str,
    real_name: str,
    id_number: str,
    phone: str,
    customer_level: str,
    manager: Employee,
    annual_income_range: str,
    total_assets: str | Decimal,
    investment_experience: str,
    target_allocation: dict | None = None,
    product_preference: dict | None = None,
    now: datetime,
) -> Customer:
    if not username or not username.strip():
        raise AppError(400, INVALID_USERNAME_MESSAGE)
    if customer_level not in CUSTOMER_LEVELS:
        raise AppError(400, INVALID_LEVEL_MESSAGE)
    if annual_income_range not in INCOME_SCORES:
        raise AppError(400, INVALID_INCOME_MESSAGE)
    if investment_experience not in EXPERIENCE_SCORES:
        raise AppError(400, INVALID_EXPERIENCE_MESSAGE)
    if not re.fullmatch(r"\d{17}[0-9Xx]", id_number):
        raise AppError(400, INVALID_ID_NUMBER_MESSAGE)
    if not _PHONE_PATTERN.fullmatch(phone):
        raise AppError(400, INVALID_PHONE_MESSAGE)
    if len(password) < 8:
        raise AppError(400, INVALID_PASSWORD_MESSAGE)
    try:
        assets = Decimal(str(total_assets))
    except InvalidOperation as exc:
        raise AppError(400, INVALID_ASSETS_MESSAGE) from exc
    if assets < 0:
        raise AppError(400, INVALID_ASSETS_MESSAGE)

    if db.scalar(select(Customer).where(Customer.username == username)):
        raise AppError(409, USERNAME_TAKEN_MESSAGE)
    if db.scalar(select(Customer).where(Customer.id_number == id_number)):
        raise AppError(409, ID_NUMBER_TAKEN_MESSAGE)

    customer = Customer(
        username=username,
        password_hash=PasswordHasher().hash(password),
        real_name=real_name,
        id_number=id_number,
        phone=phone,
        customer_level=customer_level,
        status="正常",
        manager_id=manager.id,
        opened_at=now,
    )
    db.add(customer)
    db.flush()

    # 初始画像：risk_level 先落最低档占位（列约束要求 C1-C5），真正的等级
    # 由风评问卷写回；自述字段带着「默认值」来源入库，置信度按来源初值。
    profile = CustomerProfile(
        customer_id=customer.id,
        risk_level="C1",
        risk_score=0,
        investment_experience=investment_experience,
        annual_income_range=annual_income_range,
        total_assets=assets,
        target_allocation=target_allocation or {},
        product_preference=product_preference or {},
        confidence_score=Decimal(str(SOURCE_INITIAL_CONFIDENCE[SOURCE_DEFAULT])),
        computed_at=now,
    )
    db.add(profile)
    db.flush()

    tags: dict[str, object] = {
        "risk_level": "C1",
        "investment_experience": investment_experience,
        "annual_income_range": annual_income_range,
        "total_assets": str(assets),
    }
    if target_allocation:
        tags["target_allocation"] = target_allocation
    if product_preference:
        tags["product_preference"] = product_preference
    for tag_key, value in tags.items():
        write_tag(
            db,
            cache,
            customer_id=customer.id,
            tag_key=tag_key,
            value=value,
            source=SOURCE_DEFAULT,
            now=now,
        )
    db.commit()
    db.refresh(customer)
    return customer


def serialize_account(customer: Customer) -> dict:
    return {
        "id": customer.id,
        "username": customer.username,
        "real_name": customer.real_name,
        "customer_level": customer.customer_level,
        "status": customer.status,
        "manager_id": customer.manager_id,
        "opened_at": customer.opened_at.isoformat(),
    }
