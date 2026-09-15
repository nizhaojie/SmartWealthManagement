import jwt as pyjwt
from fastapi import Depends

from app.auth import roles
from app.auth.dependencies import AuthContext, require_customer, require_employee_role, require_internal
from app.auth.tokens import issue_access_token
from app.db.models import Employee
from app.http import ok
from app.main import app
from app.settings import get_settings

CUSTOMER_USERNAME = "wangc1"
EMPLOYEE_USERNAME = "advisor1"
RISK_OFFICER_USERNAME = "risk1"
ACCOUNT_MANAGER_USERNAME = "manager1"
SEEDED_PASSWORD = "Test@1234"


@app.get("/api/__test__/customer-protected")
def _customer_protected(auth: AuthContext = Depends(require_customer)):
    return ok({"subject_id": auth.subject_id})


@app.get("/api/__test__/internal-protected")
def _internal_protected(auth: AuthContext = Depends(require_internal)):
    return ok({"subject_id": auth.subject_id})


@app.get("/api/__test__/advisor-only")
def _advisor_only(employee: Employee = Depends(require_employee_role(roles.ADVISOR))):
    return ok({"employee_role": employee.employee_role})


def _subject_id_of(access_token: str) -> int:
    return int(pyjwt.decode(access_token, options={"verify_signature": False})["sub"])


def test_customer_login_returns_access_and_refresh_tokens(auth_client):
    response = auth_client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["access_token"] != data["refresh_token"]


def test_employee_login_returns_access_and_refresh_tokens(auth_client):
    response = auth_client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["access_token"]
    assert data["refresh_token"]


def test_login_failure_does_not_distinguish_unknown_user_from_wrong_password(auth_client):
    unknown_user_response = auth_client.post(
        "/api/customer/auth/login",
        json={"username": "no-such-user", "password": SEEDED_PASSWORD},
    )
    wrong_password_response = auth_client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": "wrong-password"},
    )

    assert unknown_user_response.status_code == wrong_password_response.status_code == 401
    unknown_body = unknown_user_response.json()
    wrong_body = wrong_password_response.json()
    assert unknown_body["code"] == wrong_body["code"]
    assert unknown_body["message"] == wrong_body["message"]


def _customer_access_token(auth_client) -> str:
    response = auth_client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    return response.json()["data"]["access_token"]


def _employee_access_token(auth_client) -> str:
    response = auth_client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    return response.json()["data"]["access_token"]


def test_guardrail_customer_token_rejected_on_internal_endpoint(auth_client):
    token = _customer_access_token(auth_client)

    response = auth_client.get(
        "/api/__test__/internal-protected", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code in (401, 403)


def test_guardrail_employee_token_rejected_on_customer_endpoint(auth_client):
    token = _employee_access_token(auth_client)

    response = auth_client.get(
        "/api/__test__/customer-protected", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code in (401, 403)


def test_customer_token_is_accepted_on_customer_endpoint(auth_client):
    token = _customer_access_token(auth_client)

    response = auth_client.get(
        "/api/__test__/customer-protected", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert response.json()["data"]["subject_id"] == _subject_id_of(token)


def test_missing_credential_is_rejected_on_protected_endpoints(auth_client):
    for path in ("/api/__test__/customer-protected", "/api/__test__/internal-protected"):
        response = auth_client.get(path)
        assert response.status_code == 401

    logout_response = auth_client.post("/api/customer/auth/logout")
    assert logout_response.status_code == 401


def test_expired_access_token_is_rejected_but_refresh_token_still_works(auth_client):
    login_response = auth_client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    tokens = login_response.json()["data"]
    unverified = pyjwt.decode(tokens["access_token"], options={"verify_signature": False})
    settings = get_settings()
    expired_settings = settings.model_copy(update={"access_token_expire_minutes": -1})
    expired_access_token = issue_access_token(
        subject=unverified["sub"],
        audience=settings.customer_token_audience,
        session_id=unverified["sid"],
        settings=expired_settings,
    )

    expired_response = auth_client.get(
        "/api/__test__/customer-protected", headers={"Authorization": f"Bearer {expired_access_token}"}
    )
    assert expired_response.status_code == 401

    refresh_response = auth_client.post(
        "/api/customer/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refresh_response.status_code == 200
    new_access_token = refresh_response.json()["data"]["access_token"]

    protected_response = auth_client.get(
        "/api/__test__/customer-protected", headers={"Authorization": f"Bearer {new_access_token}"}
    )
    assert protected_response.status_code == 200
    assert protected_response.json()["data"]["subject_id"] == _subject_id_of(new_access_token)


def test_logout_invalidates_both_access_and_refresh_token(auth_client):
    login_response = auth_client.post(
        "/api/customer/auth/login",
        json={"username": CUSTOMER_USERNAME, "password": SEEDED_PASSWORD},
    )
    tokens = login_response.json()["data"]
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    logout_response = auth_client.post(
        "/api/customer/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert logout_response.status_code == 200

    protected_response = auth_client.get(
        "/api/__test__/customer-protected", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert protected_response.status_code == 401

    refresh_response = auth_client.post(
        "/api/customer/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_response.status_code == 401


def _login_employee(auth_client, username: str) -> str:
    response = auth_client.post(
        "/api/internal/auth/login",
        json={"username": username, "password": SEEDED_PASSWORD},
    )
    return response.json()["data"]["access_token"]


def test_internal_me_returns_the_authenticated_employees_identity(auth_client):
    token = _login_employee(auth_client, EMPLOYEE_USERNAME)

    response = auth_client.get("/api/internal/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data == {"real_name": "陈顾问", "employee_role": "理财顾问"}


def test_internal_logout_invalidates_the_session(auth_client):
    login_response = auth_client.post(
        "/api/internal/auth/login",
        json={"username": EMPLOYEE_USERNAME, "password": SEEDED_PASSWORD},
    )
    access_token = login_response.json()["data"]["access_token"]

    logout_response = auth_client.post(
        "/api/internal/auth/logout", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert logout_response.status_code == 200

    me_response = auth_client.get(
        "/api/internal/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me_response.status_code == 401


def test_role_restricted_endpoint_rejects_other_employee_roles(auth_client):
    advisor_token = _login_employee(auth_client, EMPLOYEE_USERNAME)
    risk_officer_token = _login_employee(auth_client, RISK_OFFICER_USERNAME)
    manager_token = _login_employee(auth_client, ACCOUNT_MANAGER_USERNAME)

    advisor_response = auth_client.get(
        "/api/__test__/advisor-only", headers={"Authorization": f"Bearer {advisor_token}"}
    )
    assert advisor_response.status_code == 200
    assert advisor_response.json()["data"]["employee_role"] == "理财顾问"

    for token in (risk_officer_token, manager_token):
        response = auth_client.get(
            "/api/__test__/advisor-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403
