from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, current_employee, require_customer, require_internal
from app.auth.schemas import AccessTokenOnly, EmployeeIdentity, LoginRequest, RefreshRequest, TokenPair
from app.auth.service import login_customer, login_employee, logout as perform_logout
from app.auth.service import refresh_customer_access_token, refresh_employee_access_token
from app.db.models import Employee
from app.db.session import get_session
from app.http import ok
from app.redis_client import get_redis
from app.settings import Settings, get_settings

router = APIRouter(prefix="/api")


@router.post("/customer/auth/login")
def customer_login(
    body: LoginRequest,
    db: Session = Depends(get_session),
    cache=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    access, refresh = login_customer(
        db, cache, username=body.username, password=body.password, settings=settings
    )
    token_pair = TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )
    return ok(token_pair.model_dump())


@router.post("/customer/auth/refresh")
def customer_refresh(
    body: RefreshRequest,
    cache=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    access = refresh_customer_access_token(cache, refresh_token=body.refresh_token, settings=settings)
    token = AccessTokenOnly(access_token=access, expires_in=settings.access_token_expire_minutes * 60)
    return ok(token.model_dump())


@router.post("/customer/auth/logout")
def customer_logout(auth: AuthContext = Depends(require_customer), cache=Depends(get_redis)):
    perform_logout(cache, auth.session_id)
    return ok(None)


@router.post("/internal/auth/login")
def internal_login(
    body: LoginRequest,
    db: Session = Depends(get_session),
    cache=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    access, refresh = login_employee(
        db, cache, username=body.username, password=body.password, settings=settings
    )
    token_pair = TokenPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.access_token_expire_minutes * 60,
    )
    return ok(token_pair.model_dump())


@router.post("/internal/auth/refresh")
def internal_refresh(
    body: RefreshRequest,
    cache=Depends(get_redis),
    settings: Settings = Depends(get_settings),
):
    access = refresh_employee_access_token(cache, refresh_token=body.refresh_token, settings=settings)
    token = AccessTokenOnly(access_token=access, expires_in=settings.access_token_expire_minutes * 60)
    return ok(token.model_dump())


@router.post("/internal/auth/logout")
def internal_logout(auth: AuthContext = Depends(require_internal), cache=Depends(get_redis)):
    perform_logout(cache, auth.session_id)
    return ok(None)


@router.get("/internal/auth/me")
def internal_me(employee: Employee = Depends(current_employee)):
    identity = EmployeeIdentity(real_name=employee.real_name, employee_role=employee.employee_role)
    return ok(identity.model_dump())
