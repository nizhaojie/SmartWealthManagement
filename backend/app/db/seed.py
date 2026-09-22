from datetime import date, datetime
from decimal import Decimal
from typing import TypedDict

from argon2 import PasswordHasher
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.customer_profile.confidence import SOURCE_QUESTIONNAIRE
from app.db.models import (
    Customer,
    CustomerProfile,
    Employee,
    FundingAccount,
    Holding,
    Product,
    ProductUnderlying,
    ProfileTag,
    RiskAssessment,
    RiskAlert,
    RiskRule,
    Transaction,
    UnderlyingAsset,
    WorkOrder,
    WorkOrderTransition,
)
from app.event_bus import NullMirrorPublisher
from app.risk_monitoring import alerting
from app.risk_monitoring.rules import RISK_RULE_SEEDS
from app.settings import get_settings

DEFAULT_PASSWORD = "Test@1234"

# 种子里的历史成交都是申购：它们是客户手里那笔持仓的来处。
HISTORICAL_TRANSACTION_TYPE = "申购"

# 回放的广播出口：seed 是个脚本，不依赖 Redis（ADR-0008 的回放语义）。
# 出站镜像就地丢弃，而「落库 → 过规则引擎」这两步照常发生——要修的正是那两步。
REPLAY_PUBLISHER = NullMirrorPublisher()


class EmployeeSeed(TypedDict):
    username: str
    real_name: str
    employee_role: str
    status: str


class ProductSeed(TypedDict):
    product_code: str
    product_name: str
    product_type: str
    risk_level: str
    expected_return: Decimal
    min_amount: Decimal
    term_days: int
    fund_manager: str
    fee_rate: Decimal
    nav: Decimal
    status: str


class UnderlyingAssetSeed(TypedDict):
    asset_code: str
    asset_name: str
    asset_category: str
    industry: str


class ProductUnderlyingSeed(TypedDict):
    product_code: str
    target_kind: str  # "asset" 指向具体标的，"product" 指向另一个产品的份额
    target_code: str
    weight: Decimal


class CustomerSeed(TypedDict):
    username: str
    real_name: str
    id_number: str
    phone: str
    customer_level: str
    status: str
    manager_username: str
    opened_at: datetime
    risk_level: str
    risk_score: int
    investment_experience: str
    annual_income_range: str
    total_assets: Decimal
    available_balance: Decimal
    target_allocation: dict[str, int]
    product_preference: dict[str, list[str]]
    confidence_score: Decimal
    computed_at: datetime
    assessment_date: date
    valid_until: date
    product_code: str
    transaction_no: str
    trade_at: datetime
    amount: Decimal
    shares: Decimal
    nav: Decimal
    fee: Decimal
    current_value: Decimal

_EMPLOYEES: tuple[EmployeeSeed, ...] = (
    {
        "username": "advisor1",
        "real_name": "陈顾问",
        "employee_role": "理财顾问",
        "status": "正常",
    },
    {
        "username": "manager1",
        "real_name": "刘经理",
        "employee_role": "客户经理",
        "status": "正常",
    },
    {
        "username": "manager2",
        "real_name": "孙经理",
        "employee_role": "客户经理",
        "status": "正常",
    },
    {
        "username": "risk1",
        "real_name": "周风控",
        "employee_role": "风控专员",
        "status": "正常",
    },
)

_PRODUCTS: tuple[ProductSeed, ...] = (
    {
        "product_code": "F000001",
        "product_name": "天枢货币基金",
        "product_type": "货币基金",
        "risk_level": "R1",
        "expected_return": Decimal("2.1000"),
        "min_amount": Decimal("1000.00"),
        "term_days": 0,
        "fund_manager": "吴宁",
        "fee_rate": Decimal("0.2500"),
        # 每位客户的历史成交就是按这个价格落下的：份额 = 金额 / 净值，两处不能各说一套。
        "nav": Decimal("1.000000"),
        "status": "在售",
    },
    {
        "product_code": "F000002",
        "product_name": "天玑债券基金",
        "product_type": "债券基金",
        "risk_level": "R2",
        "expected_return": Decimal("1.8000"),
        "min_amount": Decimal("1000.00"),
        "term_days": 0,
        "fund_manager": "郑岚",
        "fee_rate": Decimal("0.4000"),
        "nav": Decimal("1.200000"),
        "status": "在售",
    },
    {
        "product_code": "F000003",
        "product_name": "天璇混合基金",
        "product_type": "混合基金",
        "risk_level": "R3",
        "expected_return": Decimal("8.0000"),
        "min_amount": Decimal("1000.00"),
        "term_days": 0,
        "fund_manager": "冯川",
        "fee_rate": Decimal("1.2000"),
        "nav": Decimal("1.500000"),
        "status": "在售",
    },
    {
        "product_code": "F000004",
        "product_name": "天权股票基金",
        "product_type": "股票基金",
        "risk_level": "R4",
        "expected_return": Decimal("12.0000"),
        "min_amount": Decimal("1000.00"),
        "term_days": 365,
        "fund_manager": "曹越",
        "fee_rate": Decimal("1.5000"),
        "nav": Decimal("2.000000"),
        "status": "在售",
    },
    {
        "product_code": "F000005",
        "product_name": "玉衡进取基金",
        "product_type": "股票基金",
        "risk_level": "R5",
        "expected_return": Decimal("18.0000"),
        "min_amount": Decimal("5000.00"),
        "term_days": 0,
        "fund_manager": "蒋远",
        "fee_rate": Decimal("1.5000"),
        "nav": Decimal("2.500000"),
        "status": "在售",
    },
    # 这两只互为底层：成环的持有关系，用于验证穿透查询有界终止而不是挂死。
    # 停售且无人持有，因此不出现在客户可见的任何清单里。
    {
        "product_code": "F900001",
        "product_name": "回环一号 FOF",
        "product_type": "混合基金",
        "risk_level": "R3",
        "expected_return": Decimal("5.0000"),
        "min_amount": Decimal("1000.00"),
        "term_days": 0,
        "fund_manager": "邵行",
        "fee_rate": Decimal("1.0000"),
        "nav": Decimal("1.000000"),
        "status": "停售",
    },
    {
        "product_code": "F900002",
        "product_name": "回环二号 FOF",
        "product_type": "混合基金",
        "risk_level": "R3",
        "expected_return": Decimal("5.5000"),
        "min_amount": Decimal("1000.00"),
        "term_days": 0,
        "fund_manager": "邵行",
        "fee_rate": Decimal("1.0000"),
        "nav": Decimal("1.000000"),
        "status": "停售",
    },
)

_UNDERLYING_ASSETS: tuple[UnderlyingAssetSeed, ...] = (
    {"asset_code": "CASH-0001", "asset_name": "同业存单", "asset_category": "现金", "industry": "货币市场"},
    {"asset_code": "CASH-0002", "asset_name": "7 天通知存款", "asset_category": "现金", "industry": "银行存款"},
    {"asset_code": "BOND-0001", "asset_name": "22 国债 05", "asset_category": "债券", "industry": "利率债"},
    {"asset_code": "BOND-0002", "asset_name": "23 国开债 10", "asset_category": "债券", "industry": "利率债"},
    {"asset_code": "BOND-0003", "asset_name": "中铁建公司债", "asset_category": "债券", "industry": "产业债"},
    {"asset_code": "EQTY-0001", "asset_name": "沪深 300 成份股组合", "asset_category": "股票", "industry": "大盘蓝筹"},
    {"asset_code": "EQTY-0002", "asset_name": "中证 500 成份股组合", "asset_category": "股票", "industry": "中盘成长"},
    {"asset_code": "EQTY-0003", "asset_name": "港股通科技股组合", "asset_category": "股票", "industry": "科技"},
    {"asset_code": "ALTV-0001", "asset_name": "黄金 ETF", "asset_category": "另类", "industry": "贵金属"},
    {"asset_code": "ALTV-0002", "asset_name": "原油 ETF", "asset_category": "另类", "industry": "能源"},
)

# F000003 通过 F000002 / F000001 持有一层嵌套的产品，穿透后有两层；
# BOND-0001 与 CASH-0001 各有两条路径，用于验证同一底层资产的多条路径会被合并。
_PRODUCT_UNDERLYINGS: tuple[ProductUnderlyingSeed, ...] = (
    {"product_code": "F000001", "target_kind": "asset", "target_code": "CASH-0001", "weight": Decimal("0.600000")},
    {"product_code": "F000001", "target_kind": "asset", "target_code": "CASH-0002", "weight": Decimal("0.400000")},
    {"product_code": "F000002", "target_kind": "asset", "target_code": "BOND-0001", "weight": Decimal("0.450000")},
    {"product_code": "F000002", "target_kind": "asset", "target_code": "BOND-0002", "weight": Decimal("0.300000")},
    {"product_code": "F000002", "target_kind": "asset", "target_code": "BOND-0003", "weight": Decimal("0.150000")},
    {"product_code": "F000002", "target_kind": "asset", "target_code": "CASH-0001", "weight": Decimal("0.100000")},
    {"product_code": "F000003", "target_kind": "product", "target_code": "F000002", "weight": Decimal("0.300000")},
    {"product_code": "F000003", "target_kind": "product", "target_code": "F000001", "weight": Decimal("0.100000")},
    {"product_code": "F000003", "target_kind": "asset", "target_code": "EQTY-0001", "weight": Decimal("0.400000")},
    {"product_code": "F000003", "target_kind": "asset", "target_code": "BOND-0001", "weight": Decimal("0.200000")},
    {"product_code": "F000004", "target_kind": "asset", "target_code": "EQTY-0001", "weight": Decimal("0.500000")},
    {"product_code": "F000004", "target_kind": "asset", "target_code": "EQTY-0002", "weight": Decimal("0.350000")},
    {"product_code": "F000004", "target_kind": "asset", "target_code": "CASH-0001", "weight": Decimal("0.150000")},
    {"product_code": "F000005", "target_kind": "asset", "target_code": "EQTY-0002", "weight": Decimal("0.450000")},
    {"product_code": "F000005", "target_kind": "asset", "target_code": "EQTY-0003", "weight": Decimal("0.250000")},
    {"product_code": "F000005", "target_kind": "asset", "target_code": "ALTV-0001", "weight": Decimal("0.200000")},
    {"product_code": "F000005", "target_kind": "asset", "target_code": "CASH-0001", "weight": Decimal("0.100000")},
    {"product_code": "F900001", "target_kind": "product", "target_code": "F900002", "weight": Decimal("0.700000")},
    {"product_code": "F900001", "target_kind": "asset", "target_code": "CASH-0001", "weight": Decimal("0.300000")},
    {"product_code": "F900002", "target_kind": "product", "target_code": "F900001", "weight": Decimal("0.800000")},
    {"product_code": "F900002", "target_kind": "asset", "target_code": "BOND-0001", "weight": Decimal("0.200000")},
)

# 每位客户的这笔历史成交与产品共用同一套成交口径（issue 02）：份额 = 金额 / 净值、
# 手续费 = 金额 × 费率。两处对不上，演示时第一步就散架，而 `test_customer_purchase_and_redemption`
# 里有一条断言专门盯着它们一致。
_CUSTOMERS: tuple[CustomerSeed, ...] = (
    {
        "username": "wangc1",
        "real_name": "王守成",
        "id_number": "110101198803150218",
        "phone": "13800138001",
        "customer_level": "普通",
        "status": "正常",
        "manager_username": "manager1",
        "opened_at": datetime(2022, 3, 1, 10, 0, 0),
        "risk_level": "C1",
        "risk_score": 18,
        "investment_experience": "0-1年",
        "annual_income_range": "10万以下",
        "total_assets": Decimal("80000.00"),
        # 刻意留的余额不足客户：用它演示「余额不足被拒绝」——余额只有两千，
        # 而这位 C1 客户能买的产品起投一千，跨过它只需要一笔稍大的申购或转账。
        "available_balance": Decimal("2000.00"),
        "target_allocation": {"股票": 10, "债券": 40, "现金": 50, "另类": 0},
        "product_preference": {"基金": ["货币基金"]},
        "confidence_score": Decimal("0.86"),
        "computed_at": datetime(2022, 3, 16, 9, 0, 0),
        "assessment_date": date(2022, 3, 15),
        "valid_until": date(2023, 3, 15),
        "product_code": "F000001",
        "transaction_no": "TX202204100001",
        "trade_at": datetime(2022, 4, 10, 10, 30, 0),
        "amount": Decimal("20000.00"),
        "shares": Decimal("20000.0000"),
        "nav": Decimal("1.000000"),
        "fee": Decimal("50.00"),
        "current_value": Decimal("20420.00"),
    },
    {
        "username": "lisic2",
        "real_name": "李思远",
        "id_number": "310101197605220353",
        "phone": "13800138002",
        "customer_level": "金卡",
        "status": "正常",
        "manager_username": "manager1",
        "opened_at": datetime(2021, 6, 1, 9, 0, 0),
        "risk_level": "C2",
        "risk_score": 36,
        "investment_experience": "1-3年",
        "annual_income_range": "10-30万",
        "total_assets": Decimal("300000.00"),
        "available_balance": Decimal("120000.00"),
        "target_allocation": {"股票": 20, "债券": 50, "现金": 25, "另类": 5},
        "product_preference": {"基金": ["债券基金"]},
        "confidence_score": Decimal("0.88"),
        "computed_at": datetime(2021, 6, 21, 9, 0, 0),
        "assessment_date": date(2021, 6, 20),
        "valid_until": date(2022, 6, 20),
        "product_code": "F000002",
        "transaction_no": "TX202108050001",
        "trade_at": datetime(2021, 8, 5, 11, 0, 0),
        "amount": Decimal("50000.00"),
        "shares": Decimal("41666.6667"),
        "nav": Decimal("1.200000"),
        "fee": Decimal("200.00"),
        "current_value": Decimal("52000.00"),
    },
    {
        "username": "zhangc3",
        "real_name": "张衡",
        "id_number": "440106199211080474",
        "phone": "13800138003",
        "customer_level": "白金",
        "status": "正常",
        "manager_username": "manager1",
        "opened_at": datetime(2020, 4, 12, 14, 0, 0),
        "risk_level": "C3",
        "risk_score": 55,
        "investment_experience": "3-5年",
        "annual_income_range": "30-50万",
        "total_assets": Decimal("800000.00"),
        "available_balance": Decimal("1000000.00"),
        "target_allocation": {"股票": 40, "债券": 35, "现金": 15, "另类": 10},
        "product_preference": {"基金": ["混合基金"]},
        "confidence_score": Decimal("0.90"),
        "computed_at": datetime(2020, 5, 2, 9, 0, 0),
        "assessment_date": date(2020, 5, 1),
        "valid_until": date(2021, 5, 1),
        "product_code": "F000003",
        "transaction_no": "TX202006180001",
        "trade_at": datetime(2020, 6, 18, 10, 15, 0),
        "amount": Decimal("100000.00"),
        "shares": Decimal("66666.6667"),
        "nav": Decimal("1.500000"),
        "fee": Decimal("1200.00"),
        "current_value": Decimal("108000.00"),
    },
    {
        "username": "zhaoc4",
        "real_name": "赵启明",
        "id_number": "320106198412030121",
        "phone": "13800138004",
        "customer_level": "钻石",
        "status": "正常",
        "manager_username": "manager2",
        "opened_at": datetime(2019, 9, 8, 11, 0, 0),
        "risk_level": "C4",
        "risk_score": 74,
        "investment_experience": "5-10年",
        "annual_income_range": "50-100万",
        "total_assets": Decimal("3000000.00"),
        "available_balance": Decimal("2500000.00"),
        "target_allocation": {"股票": 55, "债券": 25, "现金": 10, "另类": 10},
        "product_preference": {"基金": ["股票基金"]},
        "confidence_score": Decimal("0.91"),
        "computed_at": datetime(2019, 9, 21, 9, 0, 0),
        "assessment_date": date(2019, 9, 20),
        "valid_until": date(2020, 9, 20),
        "product_code": "F000004",
        "transaction_no": "TX201911020001",
        "trade_at": datetime(2019, 11, 2, 13, 40, 0),
        "amount": Decimal("200000.00"),
        "shares": Decimal("100000.0000"),
        "nav": Decimal("2.000000"),
        "fee": Decimal("3000.00"),
        "current_value": Decimal("224000.00"),
    },
    {
        "username": "qianc5",
        "real_name": "钱远航",
        "id_number": "110105199508180297",
        "phone": "13800138005",
        "customer_level": "私行",
        "status": "正常",
        "manager_username": "manager2",
        "opened_at": datetime(2018, 1, 16, 10, 0, 0),
        "risk_level": "C5",
        "risk_score": 92,
        "investment_experience": "10年以上",
        "annual_income_range": "100万以上",
        "total_assets": Decimal("12000000.00"),
        "available_balance": Decimal("5000000.00"),
        "target_allocation": {"股票": 70, "债券": 10, "现金": 5, "另类": 15},
        "product_preference": {"基金": ["股票基金"]},
        "confidence_score": Decimal("0.93"),
        "computed_at": datetime(2018, 2, 2, 9, 0, 0),
        "assessment_date": date(2018, 2, 1),
        "valid_until": date(2019, 2, 1),
        "product_code": "F000005",
        "transaction_no": "TX201803120001",
        "trade_at": datetime(2018, 3, 12, 14, 20, 0),
        "amount": Decimal("500000.00"),
        "shares": Decimal("200000.0000"),
        "nav": Decimal("2.500000"),
        "fee": Decimal("7500.00"),
        "current_value": Decimal("590000.00"),
    },
)


def seed(database_url: str | None = None) -> None:
    url = database_url or get_settings().database_url
    engine = create_engine(url)
    hasher = PasswordHasher()
    password_hash = hasher.hash(DEFAULT_PASSWORD)
    try:
        with Session(engine) as session:
            employees = _seed_employees(session, password_hash)
            products = _seed_products(session)
            _seed_underlyings(session)
            _seed_customers(session, password_hash, products, employees)
            # 规则要先进库，再回放历史交易：规则引擎读的是 `fin_risk_rule`，
            # 顺序反了就会「回放了一场没有规则的交易」。
            _seed_risk_rules(session)
            _replay_historical_trades(session, employees, products)
            session.commit()
    finally:
        engine.dispose()


def _seed_employees(session: Session, password_hash: str) -> dict[str, Employee]:
    by_username: dict[str, Employee] = {}
    for item in _EMPLOYEES:
        employee = session.scalar(select(Employee).where(Employee.username == item["username"]))
        if employee is None:
            employee = Employee(password_hash=password_hash, **item)
            session.add(employee)
            session.flush()
        by_username[item["username"]] = employee
    return by_username


def _seed_products(session: Session) -> dict[str, Product]:
    by_code: dict[str, Product] = {}
    for item in _PRODUCTS:
        product = session.scalar(
            select(Product).where(Product.product_code == item["product_code"])
        )
        if product is None:
            product = Product(**item)
            session.add(product)
            session.flush()
        else:
            for key, value in item.items():
                if key != "product_code":
                    setattr(product, key, value)
        by_code[item["product_code"]] = product
    return by_code


def _seed_underlyings(session: Session) -> None:
    assets: dict[str, UnderlyingAsset] = {}
    for item in _UNDERLYING_ASSETS:
        asset = session.scalar(
            select(UnderlyingAsset).where(UnderlyingAsset.asset_code == item["asset_code"])
        )
        if asset is None:
            asset = UnderlyingAsset(**item)
            session.add(asset)
            session.flush()
        else:
            asset.asset_name = item["asset_name"]
            asset.asset_category = item["asset_category"]
            asset.industry = item["industry"]
        assets[item["asset_code"]] = asset

    for link in _PRODUCT_UNDERLYINGS:
        product = session.scalar(
            select(Product).where(Product.product_code == link["product_code"])
        )
        if product is None:
            continue
        child_id: int | None = None
        asset_id: int | None = None
        if link["target_kind"] == "product":
            child = session.scalar(
                select(Product).where(Product.product_code == link["target_code"])
            )
            if child is None:
                continue
            child_id = child.id
        else:
            asset = assets.get(link["target_code"])
            if asset is None:
                continue
            asset_id = asset.id

        # 一条关系只指向一个目标，因此按非空的那一列去比对即可。
        stmt = select(ProductUnderlying).where(ProductUnderlying.product_id == product.id)
        stmt = (
            stmt.where(ProductUnderlying.child_product_id == child_id)
            if child_id is not None
            else stmt.where(ProductUnderlying.underlying_asset_id == asset_id)
        )
        relation = session.scalar(stmt)
        if relation is None:
            session.add(
                ProductUnderlying(
                    product_id=product.id,
                    child_product_id=child_id,
                    underlying_asset_id=asset_id,
                    weight=link["weight"],
                )
            )
        else:
            relation.weight = link["weight"]


def _seed_customers(
    session: Session,
    password_hash: str,
    products: dict[str, Product],
    employees: dict[str, Employee],
) -> None:
    for item in _CUSTOMERS:
        customer = session.scalar(select(Customer).where(Customer.username == item["username"]))
        if customer is None:
            customer = Customer(
                username=item["username"],
                password_hash=password_hash,
                real_name=item["real_name"],
                id_number=item["id_number"],
                phone=item["phone"],
                customer_level=item["customer_level"],
                status=item["status"],
                opened_at=item["opened_at"],
            )
            session.add(customer)
            session.flush()
        # 客户关系归属人：新客户落库时设置，已有客户在重复 seed 时对齐。
        manager = employees[item["manager_username"]]
        if customer.manager_id != manager.id:
            customer.manager_id = manager.id
            session.flush()

        # 资金账户：余额的初始值来自种子，重复 seed 时把余额对齐回配置值——重新 seed
        # 等于把演示状态恢复成初始状态（应用里的充值也会一起复位）。
        account = session.scalar(
            select(FundingAccount).where(FundingAccount.customer_id == customer.id)
        )
        if account is None:
            session.add(
                FundingAccount(
                    customer_id=customer.id, available_balance=item["available_balance"]
                )
            )
        else:
            account.available_balance = item["available_balance"]

        if session.scalar(
            select(CustomerProfile).where(CustomerProfile.customer_id == customer.id)
        ) is None:
            session.add(
                CustomerProfile(
                    customer_id=customer.id,
                    risk_level=item["risk_level"],
                    risk_score=item["risk_score"],
                    investment_experience=item["investment_experience"],
                    annual_income_range=item["annual_income_range"],
                    total_assets=item["total_assets"],
                    target_allocation=item["target_allocation"],
                    product_preference=item["product_preference"],
                    confidence_score=item["confidence_score"],
                    computed_at=item["computed_at"],
                )
            )

        _seed_profile_tags(session, customer.id, item)

        if session.scalar(
            select(RiskAssessment).where(
                RiskAssessment.customer_id == customer.id,
                RiskAssessment.assessment_date == item["assessment_date"],
            )
        ) is None:
            session.add(
                RiskAssessment(
                    customer_id=customer.id,
                    assessment_date=item["assessment_date"],
                    total_score=item["risk_score"],
                    risk_level=item["risk_level"],
                    answers=[{"q": 1, "a": "A", "score": item["risk_score"]}],
                    assessor_type="人工评估",
                    valid_until=item["valid_until"],
                )
            )

        product = products[item["product_code"]]
        if session.scalar(
            select(Holding).where(
                Holding.customer_id == customer.id,
                Holding.product_id == product.id,
            )
        ) is None:
            cost = item["amount"]
            current = item["current_value"]
            profit = current - cost
            session.add(
                Holding(
                    customer_id=customer.id,
                    product_id=product.id,
                    shares=item["shares"],
                    cost_amount=cost,
                    current_value=current,
                    profit_loss=profit,
                    profit_ratio=(profit / cost * Decimal("100")).quantize(Decimal("0.0001")),
                    status="持有中",
                    create_time=item["trade_at"],
                )
            )


def _replay_historical_trades(
    session: Session,
    employees: dict[str, Employee],
    products: dict[str, Product],
) -> None:
    """把种子里的历史成交按**时间正序逐笔**走同一个入海口回放一遍。

    这是本 issue 修的那道裂缝：这些交易以前是直接写 ORM 落库的，**绕过了规则引擎**，
    于是「风控监测」在演示里空转——规则、算子、分级、预警全都齐备，却没有一笔交易
    经过它们。回放因此不另写批量脚本：每一笔都调用
    `alerting.submit_transaction_event`，与客户在界面上操作走的是**同一条**路径，
    落库、广播与规则匹配照常发生，命中就产生预警。

    预警的时间戳取该笔交易自己的时间（`now=trade_at`）。规则求值的基准本来就是交易
    自身的时间（求值函数内部不读系统时钟），因此窗口与累计类规则会按历史真实的时间线
    命中，不需要为回放改任何求值逻辑。

    经办员工取**风控专员**：这批历史数据是补录出来的既成事实——它们不经过客户侧的
    适当性与余额校验，而那是只有风控专员拿得到的口子（ADR-0018）。来源标注因此认得出
    它们（「内部补录」），与客户当场发起的交易（「客户发起」）形成对照。

    广播走 `NullMirrorPublisher`：seed 是脚本，不连 Redis；广播本来就是 fire-and-forget
    的增强（ADR-0013），回放要的是「落库 → 过规则引擎」这两步真的发生。
    """
    for item in sorted(_CUSTOMERS, key=lambda seed_item: seed_item["trade_at"]):
        _replay_one_historical_trade(session, item, employees, products)


def _replay_one_historical_trade(
    session: Session,
    item: CustomerSeed,
    employees: dict[str, Employee],
    products: dict[str, Product],
) -> None:
    """回放一笔历史成交。"""
    customer = session.scalar(select(Customer).where(Customer.username == item["username"]))
    if customer is None:
        return
    product = products[item["product_code"]]
    _discard_previous_replay(session, item["transaction_no"])
    alerting.submit_transaction_event(
        session,
        publisher=REPLAY_PUBLISHER,
        submission=alerting.TransactionSubmission(
            customer_id=customer.id,
            product_id=product.id,
            transaction_type=HISTORICAL_TRANSACTION_TYPE,
            amount=item["amount"],
            occurred_at=item["trade_at"],
            shares=item["shares"],
            nav=item["nav"],
            fee=item["fee"],
            transaction_no=item["transaction_no"],
        ),
        operator_id=employees["risk1"].id,
        now=item["trade_at"],
    )


def _discard_previous_replay(session: Session, transaction_no: str) -> None:
    """撤掉上一轮回放写下的这笔交易，以及它产生的预警与预警派生的工单。

    撤掉重放而不是跳过已有行：一是重复 seed 要能把成交口径的变化带进库里（旧库里的
    历史流水按老口径躺着，而产品详情上写的是新口径，演示时一比对就是两个数）；二是
    既有的库是在本 issue 之前建的，那五笔交易**从来没有过预警**，跳过就等于让那道裂缝
    留在演示环境里。

    预警的命中依据是命中那一刻固化的快照，所以不能在原地改金额对齐——金额一改，
    依据里的实测值就对不上了。删掉重放，结果是确定性的、与第一遍逐字一致。

    工单要一起删：`biz_work_order.source_alert_id` 指着预警，不先删它，重复 seed
    会撞外键；而且工单本来就是从这条预警派生的，预警没了它也没有来处（重新 seed
    等于恢复初始演示状态）。
    """
    transaction = session.scalar(
        select(Transaction).where(Transaction.transaction_no == transaction_no)
    )
    if transaction is None:
        return
    # 先取出标识再删：MySQL 不允许在 DELETE 的子查询里再读同一张表（错误 1093）。
    alert_ids = list(
        session.scalars(
            select(RiskAlert.id).where(
                RiskAlert.customer_id == transaction.customer_id,
                func.json_contains(RiskAlert.transaction_ids, str(transaction.id)),
            )
        ).all()
    )
    if alert_ids:
        # 工单先删：`biz_work_order.source_alert_id` 指着预警，反过来删会撞外键。
        order_ids = select(WorkOrder.id).where(WorkOrder.source_alert_id.in_(alert_ids))
        session.execute(
            delete(WorkOrderTransition).where(WorkOrderTransition.work_order_id.in_(order_ids))
        )
        session.execute(delete(WorkOrder).where(WorkOrder.source_alert_id.in_(alert_ids)))
        session.execute(delete(RiskAlert).where(RiskAlert.id.in_(alert_ids)))
    session.delete(transaction)
    session.flush()


def _seed_risk_rules(session: Session) -> None:
    """写入 20 条风控规则；只补缺失的，不回改已经存在的。

    规则一旦入库就归风控专员管：改阈值、改启停都在界面上做并留痕。seed 若去对齐
    既有记录，就会在谁都没留痕的情况下把专员调过的口径改回代码里的默认值——比不改
    更糟。代码里的定义只对首次建库生效。
    """
    existing = {rule.rule_code for rule in session.scalars(select(RiskRule)).all()}
    for spec in RISK_RULE_SEEDS:
        if spec.rule_code in existing:
            continue
        session.add(
            RiskRule(
                rule_code=spec.rule_code,
                rule_name=spec.rule_name,
                category=spec.category,
                description=spec.description,
                field=spec.field,
                operator=spec.operator,
                threshold=dict(spec.threshold),
                window_hours=spec.window_hours,
                alert_level=spec.alert_level,
                weight=spec.weight,
                enabled=spec.enabled,
            )
        )


def _seed_profile_tags(session: Session, customer_id: int, item: CustomerSeed) -> None:
    tags = (
        ("risk_level", item["risk_level"]),
        ("investment_experience", item["investment_experience"]),
        ("annual_income_range", item["annual_income_range"]),
        ("total_assets", str(item["total_assets"])),
        ("target_allocation", item["target_allocation"]),
        ("product_preference", item["product_preference"]),
    )
    for tag_key, value in tags:
        if session.scalar(
            select(ProfileTag).where(
                ProfileTag.customer_id == customer_id,
                ProfileTag.tag_key == tag_key,
            )
        ) is not None:
            continue
        session.add(
            ProfileTag(
                customer_id=customer_id,
                tag_key=tag_key,
                tag_value=value,
                source=SOURCE_QUESTIONNAIRE,
                evidence_count=0,
                observed_at=item["computed_at"],
            )
        )


if __name__ == "__main__":
    seed()
