from datetime import date, datetime
from decimal import Decimal
from typing import TypedDict

from argon2 import PasswordHasher
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.customer_profile.confidence import SOURCE_QUESTIONNAIRE
from app.db.models import (
    Customer,
    CustomerProfile,
    Employee,
    Holding,
    Product,
    ProductUnderlying,
    ProfileTag,
    RiskAssessment,
    Transaction,
    UnderlyingAsset,
)
from app.settings import get_settings

DEFAULT_PASSWORD = "Test@1234"


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
    status: str


class UnderlyingAssetSeed(TypedDict):
    asset_code: str
    asset_name: str
    asset_category: str


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
    opened_at: datetime
    risk_level: str
    risk_score: int
    investment_experience: str
    annual_income_range: str
    total_assets: Decimal
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
        "status": "停售",
    },
)

_UNDERLYING_ASSETS: tuple[UnderlyingAssetSeed, ...] = (
    {"asset_code": "CASH-0001", "asset_name": "同业存单", "asset_category": "现金"},
    {"asset_code": "CASH-0002", "asset_name": "7 天通知存款", "asset_category": "现金"},
    {"asset_code": "BOND-0001", "asset_name": "22 国债 05", "asset_category": "债券"},
    {"asset_code": "BOND-0002", "asset_name": "23 国开债 10", "asset_category": "债券"},
    {"asset_code": "BOND-0003", "asset_name": "中铁建公司债", "asset_category": "债券"},
    {"asset_code": "EQTY-0001", "asset_name": "沪深 300 成份股组合", "asset_category": "股票"},
    {"asset_code": "EQTY-0002", "asset_name": "中证 500 成份股组合", "asset_category": "股票"},
    {"asset_code": "EQTY-0003", "asset_name": "港股通科技股组合", "asset_category": "股票"},
    {"asset_code": "ALTV-0001", "asset_name": "黄金 ETF", "asset_category": "另类"},
    {"asset_code": "ALTV-0002", "asset_name": "原油 ETF", "asset_category": "另类"},
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

_CUSTOMERS: tuple[CustomerSeed, ...] = (
    {
        "username": "wangc1",
        "real_name": "王守成",
        "id_number": "110101198803150218",
        "phone": "13800138001",
        "customer_level": "普通",
        "status": "正常",
        "opened_at": datetime(2022, 3, 1, 10, 0, 0),
        "risk_level": "C1",
        "risk_score": 18,
        "investment_experience": "0-1年",
        "annual_income_range": "10万以下",
        "total_assets": Decimal("80000.00"),
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
        "fee": Decimal("0.00"),
        "current_value": Decimal("20420.00"),
    },
    {
        "username": "lisic2",
        "real_name": "李思远",
        "id_number": "310101197605220353",
        "phone": "13800138002",
        "customer_level": "金卡",
        "status": "正常",
        "opened_at": datetime(2021, 6, 1, 9, 0, 0),
        "risk_level": "C2",
        "risk_score": 36,
        "investment_experience": "1-3年",
        "annual_income_range": "10-30万",
        "total_assets": Decimal("300000.00"),
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
        "fee": Decimal("50.00"),
        "current_value": Decimal("52000.00"),
    },
    {
        "username": "zhangc3",
        "real_name": "张衡",
        "id_number": "440106199211080474",
        "phone": "13800138003",
        "customer_level": "白金",
        "status": "正常",
        "opened_at": datetime(2020, 4, 12, 14, 0, 0),
        "risk_level": "C3",
        "risk_score": 55,
        "investment_experience": "3-5年",
        "annual_income_range": "30-50万",
        "total_assets": Decimal("800000.00"),
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
        "fee": Decimal("100.00"),
        "current_value": Decimal("108000.00"),
    },
    {
        "username": "zhaoc4",
        "real_name": "赵启明",
        "id_number": "320106198412030121",
        "phone": "13800138004",
        "customer_level": "钻石",
        "status": "正常",
        "opened_at": datetime(2019, 9, 8, 11, 0, 0),
        "risk_level": "C4",
        "risk_score": 74,
        "investment_experience": "5-10年",
        "annual_income_range": "50-100万",
        "total_assets": Decimal("3000000.00"),
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
        "fee": Decimal("200.00"),
        "current_value": Decimal("224000.00"),
    },
    {
        "username": "qianc5",
        "real_name": "钱远航",
        "id_number": "110105199508180297",
        "phone": "13800138005",
        "customer_level": "私行",
        "status": "正常",
        "opened_at": datetime(2018, 1, 16, 10, 0, 0),
        "risk_level": "C5",
        "risk_score": 92,
        "investment_experience": "10年以上",
        "annual_income_range": "100万以上",
        "total_assets": Decimal("12000000.00"),
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
        "fee": Decimal("500.00"),
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
            advisor = employees["advisor1"]
            _seed_customers(session, password_hash, products, advisor.id)
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
        assets[item["asset_code"]] = asset

    for item in _PRODUCT_UNDERLYINGS:
        product = session.scalar(
            select(Product).where(Product.product_code == item["product_code"])
        )
        if product is None:
            continue
        child_id: int | None = None
        asset_id: int | None = None
        if item["target_kind"] == "product":
            child = session.scalar(
                select(Product).where(Product.product_code == item["target_code"])
            )
            if child is None:
                continue
            child_id = child.id
        else:
            asset = assets.get(item["target_code"])
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
                    weight=item["weight"],
                )
            )
        else:
            relation.weight = item["weight"]


def _seed_customers(
    session: Session,
    password_hash: str,
    products: dict[str, Product],
    operator_id: int,
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

        if session.scalar(
            select(Transaction).where(Transaction.transaction_no == item["transaction_no"])
        ) is None:
            session.add(
                Transaction(
                    transaction_no=item["transaction_no"],
                    customer_id=customer.id,
                    product_id=product.id,
                    transaction_type="申购",
                    amount=item["amount"],
                    shares=item["shares"],
                    nav=item["nav"],
                    fee=item["fee"],
                    status="已确认",
                    operator_id=operator_id,
                    create_time=item["trade_at"],
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
