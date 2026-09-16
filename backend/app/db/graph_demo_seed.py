"""演示规模的附加数据：只为知识图谱验收的规模要求存在。

`app.db.seed` 里的基础种子数据（5 个客户、7 个产品）是给其它领域测试用的
固定夹具，改不得——很多用例按精确数字断言（如 `test_schema_and_seed.py`）。
图谱验收要求节点数与关系数能撑起多跳演示（客户/产品/行业/基金经理，
见 `.scratch/knowledge-graph-and-graphrag/issues/01-graph-model-and-idempotent-rebuild.md`），
这份数据是在基础种子之上*叠加*的，不改动、不复用任何基础种子的业务键，
只在需要更大规模时单独跑：

    python -m app.db.graph_demo_seed

插入前提是 `app.db.seed.seed()` 已经跑过（需要 manager1/manager2 这两个
客户经理）。像基础种子一样按业务键做「不存在则插入」，重复执行不产生重复数据。
"""

from datetime import datetime
from decimal import Decimal
from typing import TypedDict

from argon2 import PasswordHasher
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import (
    Customer,
    CustomerProfile,
    Employee,
    Holding,
    Product,
    ProductUnderlying,
    UnderlyingAsset,
)
from app.settings import get_settings

DEFAULT_PASSWORD = "Test@1234"

# 同一基金经理只管一类产品——这既是"构造的基金经理数据与产品数据自洽"
# 的要求，也让"这位基金经理还管着哪些产品"这个多跳演示场景有内容可答。
FUND_MANAGERS: tuple[tuple[str, str], ...] = (
    ("陈牧", "货币基金"),
    ("林薇", "债券基金"),
    ("苏晴", "混合基金"),
    ("赵航", "股票基金"),
    ("周敏", "指数基金"),
    ("吴桐", "QDII基金"),
    ("郑远", "债券基金"),
    ("孙悦", "混合基金"),
    ("何俊", "股票基金"),
    ("黄磊", "货币基金"),
    ("徐乐", "指数基金"),
    ("高远", "QDII基金"),
)

_RISK_BY_TYPE = {
    "货币基金": "R1",
    "债券基金": "R2",
    "混合基金": "R3",
    "指数基金": "R3",
    "股票基金": "R4",
    "QDII基金": "R5",
}

_INDUSTRIES: tuple[str, ...] = (
    "医药", "消费", "新能源", "半导体", "军工", "有色金属", "农业", "地产",
    "公用事业", "通信", "食品饮料", "家电", "传媒", "环保", "交通运输",
)

_TIER_PROFILE: dict[int, dict] = {
    1: {
        "customer_level": "普通",
        "risk_score": 20,
        "investment_experience": "0-1年",
        "annual_income_range": "10万以下",
        "total_assets": Decimal("60000.00"),
        "target_allocation": {"股票": 10, "债券": 40, "现金": 50, "另类": 0},
        "product_preference": {"基金": ["货币基金"]},
    },
    2: {
        "customer_level": "金卡",
        "risk_score": 32,
        "investment_experience": "1-3年",
        "annual_income_range": "10-30万",
        "total_assets": Decimal("250000.00"),
        "target_allocation": {"股票": 20, "债券": 50, "现金": 25, "另类": 5},
        "product_preference": {"基金": ["债券基金"]},
    },
    3: {
        "customer_level": "白金",
        "risk_score": 42,
        "investment_experience": "3-5年",
        "annual_income_range": "30-50万",
        "total_assets": Decimal("700000.00"),
        "target_allocation": {"股票": 40, "债券": 35, "现金": 15, "另类": 10},
        "product_preference": {"基金": ["混合基金"]},
    },
    4: {
        "customer_level": "钻石",
        "risk_score": 52,
        "investment_experience": "5-10年",
        "annual_income_range": "50-100万",
        "total_assets": Decimal("2500000.00"),
        "target_allocation": {"股票": 55, "债券": 25, "现金": 10, "另类": 10},
        "product_preference": {"基金": ["股票基金"]},
    },
    5: {
        "customer_level": "私行",
        "risk_score": 80,
        "investment_experience": "10年以上",
        "annual_income_range": "100万以上",
        "total_assets": Decimal("8000000.00"),
        "target_allocation": {"股票": 70, "债券": 10, "现金": 5, "另类": 15},
        "product_preference": {"基金": ["股票基金"]},
    },
}

CUSTOMERS_PER_TIER = 8
PRODUCTS_PER_MANAGER = 2


class _AssetSeed(TypedDict):
    asset_code: str
    asset_name: str
    asset_category: str
    industry: str


def _demo_assets() -> tuple[_AssetSeed, ...]:
    assets: list[_AssetSeed] = []
    for i, industry in enumerate(_INDUSTRIES, start=1):
        for j in range(1, 3):
            assets.append(
                {
                    "asset_code": f"DEMO-A{i:02d}{j}",
                    "asset_name": f"{industry}主题股票组合{j}号",
                    "asset_category": "股票",
                    "industry": industry,
                }
            )
    return tuple(assets)


class _ProductSeed(TypedDict):
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


def _demo_products() -> tuple[_ProductSeed, ...]:
    products: list[_ProductSeed] = []
    index = 1
    for manager, product_type in FUND_MANAGERS:
        risk_level = _RISK_BY_TYPE[product_type]
        tier = int(risk_level[1:])
        for slot in range(PRODUCTS_PER_MANAGER):
            products.append(
                {
                    "product_code": f"D{index:06d}",
                    "product_name": f"{manager}{product_type}{slot + 1}号",
                    "product_type": product_type,
                    "risk_level": risk_level,
                    "expected_return": Decimal(str(1.5 + tier * 2.5)),
                    "min_amount": Decimal("1000.00"),
                    "term_days": 0 if product_type == "货币基金" else 180,
                    "fund_manager": manager,
                    "fee_rate": Decimal(str(0.2 + tier * 0.25)),
                    "status": "在售",
                }
            )
            index += 1
    return tuple(products)


def _seed_demo_underlyings(session: Session, products: dict[str, Product]) -> dict[str, UnderlyingAsset]:
    assets: dict[str, UnderlyingAsset] = {}
    for item in _demo_assets():
        asset = session.scalar(
            select(UnderlyingAsset).where(UnderlyingAsset.asset_code == item["asset_code"])
        )
        if asset is None:
            asset = UnderlyingAsset(**item)
            session.add(asset)
            session.flush()
        assets[item["asset_code"]] = asset

    demo_asset_codes = [item["asset_code"] for item in _demo_assets()]
    for i, product in enumerate(products.values()):
        primary = assets[demo_asset_codes[(2 * i) % len(demo_asset_codes)]]
        secondary = assets[demo_asset_codes[(2 * i + 1) % len(demo_asset_codes)]]
        for asset, weight in ((primary, Decimal("0.600000")), (secondary, Decimal("0.400000"))):
            relation = session.scalar(
                select(ProductUnderlying).where(
                    ProductUnderlying.product_id == product.id,
                    ProductUnderlying.underlying_asset_id == asset.id,
                )
            )
            if relation is None:
                session.add(
                    ProductUnderlying(
                        product_id=product.id,
                        underlying_asset_id=asset.id,
                        weight=weight,
                    )
                )
    return assets


def _seed_demo_products(session: Session) -> dict[str, Product]:
    by_code: dict[str, Product] = {}
    for item in _demo_products():
        product = session.scalar(
            select(Product).where(Product.product_code == item["product_code"])
        )
        if product is None:
            product = Product(**item)
            session.add(product)
            session.flush()
        by_code[item["product_code"]] = product
    return by_code


def _seed_demo_customers(
    session: Session,
    password_hash: str,
    products: dict[str, Product],
    base_products: dict[str, Product],
    employees: dict[str, Employee],
) -> None:
    managers = [employees["manager1"], employees["manager2"]]
    all_products = {**base_products, **products}

    index = 1
    for tier in range(1, 6):
        profile = _TIER_PROFILE[tier]
        eligible = sorted(
            code
            for code, product in all_products.items()
            if int(product.risk_level[1:]) <= tier
        )
        # 每个梯队只用最高风险附近的三只产品做共同持仓——覆盖面够用，
        # 又保证同一梯队里的客户会撞上同样的产品，多跳查询才有"共同持仓"可演示。
        shared_pool = eligible[-3:] if len(eligible) >= 3 else eligible

        for slot in range(CUSTOMERS_PER_TIER):
            username = f"graphdemo{index:03d}"
            customer = session.scalar(select(Customer).where(Customer.username == username))
            now = datetime(2024, 1, 1, 9, 0, 0)
            if customer is None:
                customer = Customer(
                    username=username,
                    password_hash=password_hash,
                    real_name=f"演示客户{index:03d}",
                    id_number=f"91{tier}1011990{index:07d}",
                    phone=f"139{index:08d}",
                    customer_level=profile["customer_level"],
                    status="正常",
                    manager_id=managers[index % 2].id,
                    opened_at=now,
                )
                session.add(customer)
                session.flush()

            if session.scalar(
                select(CustomerProfile).where(CustomerProfile.customer_id == customer.id)
            ) is None:
                session.add(
                    CustomerProfile(
                        customer_id=customer.id,
                        risk_level=f"C{tier}",
                        risk_score=profile["risk_score"],
                        investment_experience=profile["investment_experience"],
                        annual_income_range=profile["annual_income_range"],
                        total_assets=profile["total_assets"],
                        target_allocation=profile["target_allocation"],
                        product_preference=profile["product_preference"],
                        confidence_score=Decimal("0.85"),
                        computed_at=now,
                    )
                )

            held_codes = {shared_pool[slot % len(shared_pool)], shared_pool[(slot + 1) % len(shared_pool)]}
            for code in held_codes:
                product = all_products[code]
                if session.scalar(
                    select(Holding).where(
                        Holding.customer_id == customer.id, Holding.product_id == product.id
                    )
                ) is not None:
                    continue
                cost = Decimal("10000.00")
                current = Decimal("10200.00")
                session.add(
                    Holding(
                        customer_id=customer.id,
                        product_id=product.id,
                        shares=Decimal("10000.0000"),
                        cost_amount=cost,
                        current_value=current,
                        profit_loss=current - cost,
                        profit_ratio=((current - cost) / cost * Decimal("100")).quantize(
                            Decimal("0.0001")
                        ),
                        status="持有中",
                        create_time=now,
                    )
                )

            index += 1


def seed_graph_demo(database_url: str | None = None) -> None:
    url = database_url or get_settings().database_url
    engine = create_engine(url)
    hasher = PasswordHasher()
    password_hash = hasher.hash(DEFAULT_PASSWORD)
    try:
        with Session(engine) as session:
            employees = {
                username: session.scalar(select(Employee).where(Employee.username == username))
                for username in ("manager1", "manager2")
            }
            missing = [name for name, employee in employees.items() if employee is None]
            if missing:
                raise RuntimeError(
                    f"缺少客户经理 {missing}，请先运行 app.db.seed.seed() 生成基础种子数据"
                )
            confirmed_employees: dict[str, Employee] = {
                name: employee for name, employee in employees.items() if employee is not None
            }

            base_products = {
                row.product_code: row
                for row in session.scalars(select(Product))
            }

            demo_products = _seed_demo_products(session)
            session.flush()
            _seed_demo_underlyings(session, demo_products)
            _seed_demo_customers(
                session, password_hash, demo_products, base_products, confirmed_employees
            )
            session.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    seed_graph_demo()
