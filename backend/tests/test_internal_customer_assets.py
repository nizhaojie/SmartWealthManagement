"""顾问侧读取客户持仓（issue 05）：画像面板的目标/实际配置对比图需要它。

Seam：后端 HTTP 层。持仓聚合本身已经在 test_customer_assets.py 覆盖过，
这里只测新增的内部路由的可见范围与角色限制。
"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Customer
from app.settings import get_settings

ADVISOR = "advisor1"
ACCOUNT_MANAGER = "manager1"
SEEDED_PASSWORD = "Test@1234"
CUSTOMER_A = "wangc1"


def _engine():
    return create_engine(get_settings().test_database_url)


def _customer_id(username: str) -> int:
    with OrmSession(_engine()) as session:
        customer = session.scalar(select(Customer).where(Customer.username == username))
        assert customer is not None
        return customer.id


def _employee_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def _customer_headers(client: TestClient, username: str) -> dict[str, str]:
    response = client.post(
        "/api/customer/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def test_an_advisor_can_read_a_customers_holdings(auth_client: TestClient):
    response = auth_client.get(
        f"/api/internal/customers/{_customer_id(CUSTOMER_A)}/assets",
        headers=_employee_headers(auth_client, ADVISOR),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["holding_count"] == 1
    assert {item["product_code"] for item in data["holdings"]} == {"F000001"}


def test_an_account_manager_can_also_read_a_customers_holdings(auth_client: TestClient):
    response = auth_client.get(
        f"/api/internal/customers/{_customer_id(CUSTOMER_A)}/assets",
        headers=_employee_headers(auth_client, ACCOUNT_MANAGER),
    )

    assert response.status_code == 200


def test_a_customer_token_cannot_read_the_internal_assets_route(auth_client: TestClient):
    response = auth_client.get(
        f"/api/internal/customers/{_customer_id(CUSTOMER_A)}/assets",
        headers=_customer_headers(auth_client, CUSTOMER_A),
    )

    assert response.status_code in (401, 403)
