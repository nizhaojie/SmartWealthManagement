"""客户经理按 customer_id 读画像与持仓的可见范围。

Seam：后端 HTTP 层。这两个入口的客户标识来自**路径**而不是凭证，因此「前端没给入口」
不构成约束——只做 require_internal 的话，客户经理按 id 拼一个 URL 就能读到非名下客户的
画像与持仓。可见范围与审核内容、工单、预警、资金账户、会话归档同一条口径
（`app.customer_scope`）：客户经理只看得到自己名下客户，理财顾问与风控专员不受限。

种子里的归属（`app.db.seed`）：manager1 名下 wangc1 / lisic2 / zhangc3，manager2 名下
zhaoc4 / qianc5。两个方向都试一遍，避免「只有一侧写对了」也算通过。
"""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session as OrmSession

from app.customer_profile.confidence import SOURCE_QUESTIONNAIRE
from app.db.models import Customer, CustomerProfile, ProfileTag, ProfileTagConflict
from app.settings import get_settings

ADVISOR = "advisor1"
RISK_OFFICER = "risk1"
MANAGER_1 = "manager1"
MANAGER_2 = "manager2"
SEEDED_PASSWORD = "Test@1234"

WANGC_1 = "wangc1"
ZHAOC_4 = "zhaoc4"

TAG_KEY = "investment_experience"

# (读的人, 被读的客户, 这次是不是越权)
SCOPE_CASES = (
    (MANAGER_2, WANGC_1, True),
    (MANAGER_1, ZHAOC_4, True),
    (MANAGER_1, WANGC_1, False),
    (ADVISOR, WANGC_1, False),
    (RISK_OFFICER, ZHAOC_4, False),
)


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


def _customer_paths(customer_id: int) -> tuple[str, str]:
    return (
        f"/api/internal/customers/{customer_id}/profile",
        f"/api/internal/customers/{customer_id}/assets",
    )


@pytest.mark.parametrize("viewer, target, forbidden", SCOPE_CASES)
def test_profile_and_assets_follow_customer_ownership(
    auth_client: TestClient, viewer: str, target: str, forbidden: bool
):
    headers = _employee_headers(auth_client, viewer)

    for path in _customer_paths(_customer_id(target)):
        response = auth_client.get(path, headers=headers)
        expected = 403 if forbidden else 200
        assert response.status_code == expected, f"{viewer} → {path}: {response.text}"


def _snapshot_tag(customer_id: int) -> dict | None:
    with OrmSession(_engine()) as session:
        row = session.scalar(
            select(ProfileTag).where(
                ProfileTag.customer_id == customer_id, ProfileTag.tag_key == TAG_KEY
            )
        )
        profile = session.scalar(
            select(CustomerProfile).where(CustomerProfile.customer_id == customer_id)
        )
        if row is None:
            return None
        return {
            "tag_value": row.tag_value,
            "source": row.source,
            "evidence_count": row.evidence_count,
            "observed_at": row.observed_at,
            "expired": row.expired,
            "reason": row.reason,
            "profile_field": getattr(profile, TAG_KEY) if profile else None,
        }


def _restore_tag(customer_id: int, snapshot: dict | None, since: datetime) -> None:
    """把这次请求可能写下的东西原样撤回（见下面用例的说明）。

    只有在闸门被重新打开（也就是本用例红了）时才有东西可撤；撤干净是为了让
    「红一次」不把测试库留在半改状态里，污染同一批用例的其余部分。
    """
    with OrmSession(_engine()) as session:
        session.execute(
            delete(ProfileTagConflict).where(
                ProfileTagConflict.customer_id == customer_id,
                ProfileTagConflict.tag_key == TAG_KEY,
                ProfileTagConflict.changed_at >= since,
            )
        )
        row = session.scalar(
            select(ProfileTag).where(
                ProfileTag.customer_id == customer_id, ProfileTag.tag_key == TAG_KEY
            )
        )
        if snapshot is None:
            if row is not None:
                session.delete(row)
        else:
            row.tag_value = snapshot["tag_value"]
            row.source = snapshot["source"]
            row.evidence_count = snapshot["evidence_count"]
            row.observed_at = snapshot["observed_at"]
            row.expired = snapshot["expired"]
            row.reason = snapshot["reason"]
            profile = session.scalar(
                select(CustomerProfile).where(CustomerProfile.customer_id == customer_id)
            )
            if profile is not None:
                setattr(profile, TAG_KEY, snapshot["profile_field"])
        session.commit()


def test_an_unrelated_account_manager_cannot_write_profile_tags(auth_client: TestClient):
    # 写入这条路径不只改标签：响应里会把整份画像原样带回来，因此放开它等于把
    # 上面那道读的闸门从后门绕过去。
    customer_id = _customer_id(WANGC_1)
    snapshot = _snapshot_tag(customer_id)
    since = datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        response = auth_client.put(
            f"/api/internal/customers/{customer_id}/profile/tags",
            headers=_employee_headers(auth_client, MANAGER_2),
            json={"tag_key": TAG_KEY, "value": "10年以上", "source": SOURCE_QUESTIONNAIRE},
        )

        assert response.status_code == 403, response.text
    finally:
        _restore_tag(customer_id, snapshot, since)
