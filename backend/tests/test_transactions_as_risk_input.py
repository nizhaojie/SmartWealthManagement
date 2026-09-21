"""交易成为风控的真正输入（issue 04）。

风控那一侧本来就是完整的，缺的是输入端：交易事件在应用里没有触发点，种子数据又整批
绕过了规则引擎。这一份钉住四件事：

1. **客户发起一笔 50 万转账 → 预警列表出现对应预警**（本 slice 的验收标准）；
2. 预警的来源可分辨——客户发起 / 内部补录，依据是关联交易有没有经办员工（Q22），
   依据本身不新增字段；
3. 广播通道不可用时，**客户侧**发起的交易与预警照常落库（既有断言换到客户侧入口上
   再跑一遍）；
4. 种子里的历史交易按时间正序逐笔走**同一个**入海口回放，预警时间戳取交易自己的
   时间，回放结果与逐笔走一遍规则引擎一致。

内部补录只对风控专员开放（ADR-0018、ADR-0009 的护栏 7）的断言在
`tests/test_transaction_events_api.py`——那是补录入口自己的用例文件。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select, text
from sqlalchemy.orm import Session as OrmSession

import app.db.seed as seed_module
from app.db.migrate import apply_schema
from app.db.models import (
    Customer,
    FundingAccount,
    Holding,
    Product,
    RiskAlert,
    Transaction,
    Transfer,
)
from app.db.seed import seed
from app.event_bus import NullMirrorPublisher, get_event_publisher
from app.main import app
from app.risk_monitoring import alerting, service as risk_service
from app.risk_monitoring.alerting import SOURCE_CUSTOMER, SOURCE_INTERNAL_BACKFILL
from app.risk_monitoring.context import TransactionEvent
from app.risk_monitoring.evaluator import match_rules
from app.settings import get_settings

SEEDED_PASSWORD = "Test@1234"
RISK_OFFICER = "risk1"

TRANSFER_PATH = "/api/customer/transactions/transfer"
ALERTS_PATH = "/api/internal/risk-alerts"

# 本文件造出来的事实都落在 2026 年之后；种子回放进来的历史事实在 2018 年到 2022 年。
TEST_EPOCH = datetime(2026, 1, 1)

CUSTOMER = "zhangc3"  # C3，可用余额 100 万：转得动 50 万
CUSTOMER_BACKFILL = "lisic2"
PRODUCT_R3 = "F000003"

PAYEE_NAME = "李四"
PAYEE_ACCOUNT = "6222020200112233445"

SCRATCH_DB = "wealth_replay_history_test"


class _BrokenPublisher:
    """模拟事件总线不可用：通道掉线时发布就是会抛。"""

    def publish(self, event) -> None:
        raise ConnectionError("事件总线不可用")


def _engine():
    return create_engine(get_settings().test_database_url)


def _customer_id(engine, username: str) -> int:
    with OrmSession(engine) as session:
        value = session.scalar(select(Customer.id).where(Customer.username == username))
    assert value is not None
    return int(value)


def _internal_headers(client: TestClient, username: str = RISK_OFFICER) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _customer_headers(client: TestClient, username: str = CUSTOMER) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _transfer(client: TestClient, *, amount: str, username: str = CUSTOMER, **extra):
    return client.post(
        TRANSFER_PATH,
        headers=_customer_headers(client, username),
        json={
            "payee_name": PAYEE_NAME,
            "payee_account": PAYEE_ACCOUNT,
            "amount": amount,
            **extra,
        },
    )


def _list_alerts(client: TestClient, headers: dict[str, str]) -> list[dict]:
    response = client.get(ALERTS_PATH, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _detail(client: TestClient, headers: dict[str, str], alert_id: int) -> dict:
    response = client.get(f"{ALERTS_PATH}/{alert_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def _purge(engine) -> None:
    with OrmSession(engine) as session:
        session.execute(delete(RiskAlert).where(RiskAlert.create_time >= TEST_EPOCH))
        session.execute(delete(Transaction).where(Transaction.create_time >= TEST_EPOCH))
        session.execute(delete(Transfer).where(Transfer.create_time >= TEST_EPOCH))
        session.commit()


def _snapshot(engine) -> dict:
    """成交会改余额与持仓；跑完要把演示的起点放回去。"""
    with OrmSession(engine) as session:
        balances = {
            row.customer_id: row.available_balance
            for row in session.scalars(select(FundingAccount)).all()
        }
        holdings = [
            {
                "id": row.id,
                "shares": row.shares,
                "cost_amount": row.cost_amount,
                "current_value": row.current_value,
                "profit_loss": row.profit_loss,
                "profit_ratio": row.profit_ratio,
                "status": row.status,
            }
            for row in session.scalars(select(Holding)).all()
        ]
    return {"balances": balances, "holdings": holdings}


def _restore(engine, snapshot: dict) -> None:
    _purge(engine)
    with OrmSession(engine) as session:
        for customer_id, balance in snapshot["balances"].items():
            account = session.scalar(
                select(FundingAccount).where(FundingAccount.customer_id == customer_id)
            )
            if account is not None:
                account.available_balance = balance

        known = {row["id"] for row in snapshot["holdings"]}
        for row in session.scalars(select(Holding)).all():
            if row.id not in known:
                session.delete(row)
        for saved in snapshot["holdings"]:
            holding = session.get(Holding, saved["id"])
            if holding is None:
                continue
            holding.shares = saved["shares"]
            holding.cost_amount = saved["cost_amount"]
            holding.current_value = saved["current_value"]
            holding.profit_loss = saved["profit_loss"]
            holding.profit_ratio = saved["profit_ratio"]
            holding.status = saved["status"]
        session.commit()


@pytest.fixture(autouse=True)
def _clean_trade_state(auth_client: TestClient) -> Iterator[None]:
    engine = _engine()
    _purge(engine)
    before = _snapshot(engine)
    try:
        yield
    finally:
        _restore(engine, before)
        engine.dispose()


@contextmanager
def _use_publisher(publisher) -> Iterator[None]:
    app.dependency_overrides[get_event_publisher] = lambda: publisher
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_event_publisher, None)


# ---------------------------------------------------------------------------
# 验收标准：客户发起一笔 50 万转账 → 预警列表出现对应预警
# ---------------------------------------------------------------------------


def test_a_customer_transfer_shows_up_in_the_alert_list(auth_client: TestClient):
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER)
    officer = _internal_headers(auth_client)

    response = _transfer(auth_client, amount="500000.00")
    assert response.status_code == 200, response.text

    rows = [row for row in _list_alerts(auth_client, officer) if row["customer_id"] == customer_id]
    assert rows, "这笔转账没有在预警列表里出现"
    alert = rows[0]
    # 五十万的大额转账命中的是金额类规则，规则引擎不认类型也能判。
    assert "R001" in alert["rule_codes"]
    assert alert["source"] == SOURCE_CUSTOMER
    assert alert["work_order_id"] is None
    # 当场这一笔排在最上面，回放出来的历史预警按时间自然沉底——它们没有任何特殊
    # 标记或隔离，靠的就是时间倒序。
    assert all(
        row["created_at"] < alert["created_at"]
        for row in rows
        if row["source"] == SOURCE_INTERNAL_BACKFILL
    )

    detail = _detail(auth_client, officer, alert["id"])
    assert detail["source"] == SOURCE_CUSTOMER
    # 转账没有 `fin_transaction` 行（ADR-0019）：关联交易为空，金额仍在命中依据里。
    assert detail["transactions"] == []
    assert "500000" in detail["trigger_detail"]


def test_a_broken_bus_does_not_stop_a_customer_trade_or_its_alert(auth_client: TestClient):
    """广播通道不可用时：交易照常落库，预警照常产生。

    这是既有断言换到**客户侧入口**上再跑一遍——交易的常规入口是受理，
    内部补录只是修复与演示用的窄口。
    """
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER)

    with _use_publisher(_BrokenPublisher()):
        response = _transfer(auth_client, amount="60000.00")

    assert response.status_code == 200, response.text
    transfer_no = response.json()["data"]["transaction"]["transaction_no"]

    with OrmSession(engine) as session:
        persisted = session.scalar(
            select(Transfer).where(Transfer.transfer_no == transfer_no)
        )
        alerts = list(
            session.scalars(
                select(RiskAlert).where(
                    RiskAlert.customer_id == customer_id,
                    RiskAlert.create_time >= TEST_EPOCH,
                )
            ).all()
        )

    assert persisted is not None
    assert alerts, "广播失败不该让预警消失"


# ---------------------------------------------------------------------------
# 来源标注：客户发起 / 内部补录
# ---------------------------------------------------------------------------


def test_a_customer_trade_is_marked_as_customer_initiated(auth_client: TestClient):
    """客户自助发起的交易没有经办员工（Q22），预警因此标成「客户发起」。

    这里直接落一行客户发起的交易与一条关联它的预警：分辨依据只有 `operator_id`
    的有无，两个分支的取值在库里本来就是可空的，不必绕受理一圈才能造出这个状态。
    """
    engine = _engine()
    customer_id = _customer_id(engine, CUSTOMER)
    officer = _internal_headers(auth_client)
    with OrmSession(engine) as session:
        product_id = session.scalar(
            select(Product.id).where(Product.product_code == PRODUCT_R3)
        )
        transaction = Transaction(
            transaction_no="TX-SOURCE-CUSTOMER",
            customer_id=customer_id,
            product_id=product_id,
            transaction_type="申购",
            amount=Decimal("60000.00"),
            shares=Decimal("40000.0000"),
            nav=Decimal("1.500000"),
            fee=Decimal("720.00"),
            status="已确认",
            operator_id=None,
            create_time=datetime(2026, 9, 10, 11, 0, 0),
        )
        session.add(transaction)
        session.flush()
        alert = RiskAlert(
            customer_id=customer_id,
            alert_type="大额交易",
            alert_level="轻度",
            confidence=Decimal("0.10"),
            rule_codes=["R001"],
            trigger_detail="单笔大额交易（R001）：交易金额 60000 ≥ 阈值 50000",
            transaction_ids=[transaction.id],
            status="未处理",
            handler_id=None,
            handle_result=None,
            create_time=datetime(2026, 9, 10, 11, 0, 0),
            update_time=datetime(2026, 9, 10, 11, 0, 0),
        )
        session.add(alert)
        session.commit()
        alert_id = alert.id

    assert _detail(auth_client, officer, alert_id)["source"] == SOURCE_CUSTOMER
    assert _list_alerts(auth_client, officer)[0]["source"] == SOURCE_CUSTOMER


def test_a_backfilled_trade_is_marked_as_internal(auth_client: TestClient):
    """内部补录必带经办员工（ADR-0018），预警因此标成「内部补录」。

    这条也把「交易的来源不加字段」钉住：列表与详情给出的来源全部由
    `fin_transaction.operator_id` 推导，没有任何一列存着来源本身。
    """
    engine = _engine()
    officer = _internal_headers(auth_client)
    with OrmSession(engine) as session:
        customer_id = session.scalar(
            select(Customer.id).where(Customer.username == CUSTOMER_BACKFILL)
        )
        product_id = session.scalar(
            select(Product.id).where(Product.product_code == PRODUCT_R3)
        )

    response = auth_client.post(
        "/api/internal/transaction-events",
        headers=officer,
        json={
            "customer_id": customer_id,
            "product_id": product_id,
            "transaction_type": "申购",
            "amount": "60000.00",
            "occurred_at": datetime(2026, 9, 10, 11, 0, 0).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    alert_id = response.json()["data"]["alerts"][0]["id"]

    assert _detail(auth_client, officer, alert_id)["source"] == SOURCE_INTERNAL_BACKFILL
    rows = {row["id"]: row for row in _list_alerts(auth_client, officer)}
    assert rows[alert_id]["source"] == SOURCE_INTERNAL_BACKFILL


# ---------------------------------------------------------------------------
# 种子回放：历史交易走同一个入海口
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def scratch_url() -> Iterator[str]:
    """独立 scratch 库：回放要看的是整库的初始状态，不能与其它用例共底。"""
    settings = get_settings()
    root_engine = create_engine(settings.mysql_root_url)
    with root_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH_DB}"))
        conn.execute(text(f"CREATE DATABASE {SCRATCH_DB}"))
        conn.execute(text(f"GRANT ALL PRIVILEGES ON {SCRATCH_DB}.* TO 'wealth_app'@'%'"))
        conn.execute(text("FLUSH PRIVILEGES"))
        conn.commit()
    root_engine.dispose()

    url = settings.database_url.rsplit("/", 1)[0] + f"/{SCRATCH_DB}"
    apply_schema(url)
    yield url

    root_engine = create_engine(settings.mysql_root_url)
    with root_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {SCRATCH_DB}"))
        conn.commit()
    root_engine.dispose()


def _scratch_engine(url: str):
    return create_engine(url)


def test_seed_replays_every_historical_trade_through_the_same_function(
    scratch_url: str, monkeypatch: pytest.MonkeyPatch
):
    """回放不走旁路：每一笔历史成交都调用 `submit_transaction_event`。

    「回放结果与逐笔调用同一函数的结果一致」有两种钉法，这里两个都上：先证明调用
    次数与顺序（同一个函数的正序逐笔），再独立地把规则引擎重算一遍，证明库里那条
    预警确实就是这笔交易过引擎的结果。下一个人为了「快一点」再写一个批量脚本时，
    第一条断言会当场红。
    """
    calls: list = []
    original = alerting.submit_transaction_event

    def spy(db, *, publisher, submission, operator_id, now):
        calls.append((submission, operator_id, now))
        return original(
            db, publisher=publisher, submission=submission, operator_id=operator_id, now=now
        )

    monkeypatch.setattr(alerting, "submit_transaction_event", spy)
    seed(scratch_url)

    assert len(calls) == len(seed_module._CUSTOMERS)
    occurred = [submission.occurred_at for submission, _operator, _now in calls]
    assert occurred == sorted(occurred), "回放没有按时间正序逐笔"
    # 预警的时间戳取该笔交易自己的时间，而不是回放发生的时刻。
    assert [now for _submission, _operator, now in calls] == occurred

    engine = _scratch_engine(scratch_url)
    try:
        with OrmSession(engine) as session:
            rules = risk_service.enabled_rule_specs(session)
            lookback = alerting.history_lookback_hours(rules)
            alert_ids = {
                alert.id: alert
                for alert in session.scalars(select(RiskAlert)).all()
            }
            assert alert_ids, "回放没有产生任何预警"
            for transaction in session.scalars(
                select(Transaction).order_by(Transaction.create_time.asc())
            ).all():
                event = TransactionEvent(
                    transaction_id=transaction.id,
                    customer_id=transaction.customer_id,
                    product_id=transaction.product_id,
                    transaction_type=transaction.transaction_type,
                    amount=transaction.amount,
                    occurred_at=transaction.create_time,
                )
                expected = sorted(
                    hit.rule_code
                    for hit in match_rules(
                        rules,
                        alerting.build_context(session, event, lookback_hours=lookback),
                    )
                )
                matched = [
                    alert
                    for alert in alert_ids.values()
                    if transaction.id in (alert.transaction_ids or [])
                ]
                if not expected:
                    assert matched == [], "这笔交易不该有预警"
                    continue
                assert len(matched) == 1
                assert sorted(matched[0].rule_codes) == expected
                assert matched[0].create_time == transaction.create_time
                # 回放产生的历史预警不做任何特殊化：初始状态与实时产生的预警一模一样，
                # 不标记、不隔离，只有时间戳是过去的。
                assert matched[0].status == "未处理"
                assert matched[0].handler_id is None
    finally:
        engine.dispose()


def test_seeding_twice_leaves_the_same_history(scratch_url: str):
    """重复 seed 等于恢复初始演示状态：交易与预警都不会翻倍。"""
    seed(scratch_url)
    first = _history_counts(scratch_url)
    assert first["transactions"] == len(seed_module._CUSTOMERS)
    assert first["alerts"] > 0

    seed(scratch_url)

    assert _history_counts(scratch_url) == first


def test_a_replayed_alert_counts_toward_grading_history(scratch_url: str):
    """写下来并接受的副作用：回放出来的历史预警计入分级的历史计数。

    同一个客户、同一笔多规则交叉的交易——没有那条历史预警时是中度，有它就是重度。
    两次判定之间必须把前一次造出来的预警也清掉：分级只看「此前有没有被记录过」
    （布尔），留着它的话第二次判定即使没有回放历史也是重度，这条断言就什么都没钉住。

    这不是缺陷：分级看的本来就是「这一笔命中了多少条」加上「这位客户被记录过什么」，
    演示里第一笔大额操作很可能直接判重度，讲之前先把这句台词想好。
    """
    seed(scratch_url)
    engine = _scratch_engine(scratch_url)
    try:
        with OrmSession(engine) as session:
            customer_id = int(
                session.scalar(select(Customer.id).where(Customer.username == "qianc5"))
            )
            # 起点干净：这位客户的分级历史从零开始。
            _erase_customer_history(session, customer_id)

            without_history = _big_trade_level(
                session, customer_id=customer_id, at=datetime(2026, 9, 10, 9, 0, 0)
            )
            assert without_history == "中度"

            # 第二次判定只面对「回放出来的历史」这一条依据。
            _erase_customer_history(session, customer_id)

        # 重新 seed 把回放出来的历史预警放回去（重复 seed 就是恢复初始状态）。
        seed(scratch_url)

        with OrmSession(engine) as session:
            # 此刻这位客户的历史只有一条，就是回放出来的那条（2018 年那笔历史成交）。
            standing = session.scalar(
                select(func.count())
                .select_from(RiskAlert)
                .where(RiskAlert.customer_id == customer_id)
            )
            assert standing == 1

            with_history = _big_trade_level(
                session, customer_id=customer_id, at=datetime(2026, 9, 10, 10, 0, 0)
            )
            assert with_history == "重度", "回放出来的历史预警没有计入分级的历史计数"
    finally:
        engine.dispose()


def _erase_customer_history(session: OrmSession, customer_id: int) -> None:
    """清掉这位客户的全部预警与本次造出来的交易：分级历史的起点归零。"""
    session.execute(delete(RiskAlert).where(RiskAlert.customer_id == customer_id))
    session.execute(
        delete(Transaction).where(
            Transaction.customer_id == customer_id,
            Transaction.create_time >= TEST_EPOCH,
        )
    )
    session.commit()


def _big_trade_level(session: OrmSession, *, customer_id: int, at: datetime) -> str:
    """给这位客户来一笔必然多规则交叉的大额申购，返回预警等级。"""
    product_id = int(
        session.scalar(select(Product.id).where(Product.product_code == "F000004"))
    )
    _transaction, alerts = alerting.submit_transaction_event(
        session,
        publisher=NullMirrorPublisher(),
        submission=alerting.TransactionSubmission(
            customer_id=customer_id,
            product_id=product_id,
            transaction_type="申购",
            amount=Decimal("2000000.00"),
            occurred_at=at,
            transaction_no=f"TX-GRADING-{at:%Y%m%d%H%M%S}",
        ),
        operator_id=None,
        now=at,
    )
    assert alerts
    return alerts[0].alert_level


def _history_counts(url: str) -> dict[str, int]:
    engine = _scratch_engine(url)
    try:
        with OrmSession(engine) as session:
            return {
                "transactions": int(
                    session.scalar(select(func.count()).select_from(Transaction)) or 0
                ),
                "alerts": int(session.scalar(select(func.count()).select_from(RiskAlert)) or 0),
            }
    finally:
        engine.dispose()
