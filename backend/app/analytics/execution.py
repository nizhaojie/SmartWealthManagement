"""用受限执行账号运行通过校验的查询。

- 执行账号只对语义视图有 SELECT 权限（ticket 01），访问视图外对象在
  MySQL 层即被拒绝，这里把它映射为业务错误码而不是 500；
- 执行前在同一连接上 ``apply_identity`` 设置当前身份（员工或客户，由
  调用方给出，ADR-0025），归还连接池前 ``reset_analytics_identity``
  清理——会话变量跟随连接，不清理会让下一个借用该连接的请求继承上一个人
  的行级范围；
- 查询超时上限：``SESSION max_execution_time``（毫秒），超时映射为
  业务错误码；
- 结果行数上限：``fetchmany(max_rows + 1)``，超出即截断并置 truncated
  标记。PyMySQL 默认会把结果集缓冲到客户端，这里的上限守的是「返回
  给员工的行数」，不是服务端执行代价。
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.analytics.errors import (
    EXECUTION_FAILED_CODE,
    EXECUTION_FAILED_MESSAGE,
    QUERY_TIMEOUT_CODE,
    QUERY_TIMEOUT_MESSAGE,
)
from app.db.analytics_account import (
    AnalyticsIdentity,
    analytics_url_for,
    apply_identity,
    reset_analytics_identity,
)
from app.exceptions import AppError
from app.settings import Settings

logger = logging.getLogger("app")

# MySQL ER_QUERY_TIMEOUT：超过 max_execution_time 的 SELECT 被打断。
_QUERY_TIMEOUT_ERRNO = 3024


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool


@lru_cache
def _engine(analytics_url: str) -> Engine:
    return create_engine(analytics_url, pool_pre_ping=True)


def engine_for(base_url: str, settings: Settings) -> Engine:
    """受限执行账号的连接池（按库缓存；身份在每次借用时设置、归还前清理）。"""
    return _engine(
        analytics_url_for(
            base_url, settings.analytics_db_user, settings.analytics_db_password
        )
    )


def base_url_of(db: Session) -> str:
    """从应用会话的连接推导目标库，保证与分析查询落在同一个库上。"""
    bind = db.get_bind()
    engine = bind if isinstance(bind, Engine) else bind.engine
    # str(url) 会隐藏口令，但 analytics_url_for 会整体替换账号与口令。
    return str(engine.url)


def execute_query(
    base_url: str,
    sql: str,
    *,
    identity: AnalyticsIdentity,
    settings: Settings,
) -> QueryResult:
    engine = engine_for(base_url, settings)
    with engine.connect() as connection:
        try:
            apply_identity(connection, identity)
            connection.execute(
                text(
                    "SET SESSION max_execution_time ="
                    f" {int(settings.analytics_query_timeout_ms)}"
                )
            )
            cursor = connection.execute(text(sql))
            rows = cursor.fetchmany(settings.analytics_max_rows + 1)
            truncated = len(rows) > settings.analytics_max_rows
            return QueryResult(
                columns=[str(column) for column in cursor.keys()],
                rows=[
                    [_json_value(value) for value in row]
                    for row in rows[: settings.analytics_max_rows]
                ],
                truncated=truncated,
            )
        except DBAPIError as exc:
            if _is_timeout(exc):
                raise AppError(QUERY_TIMEOUT_CODE, QUERY_TIMEOUT_MESSAGE) from exc
            # 权限拒绝（访问视图外对象）也走这里：记录细节，对外只给业务错误码。
            logger.warning("analytics query failed: %s", exc)
            raise AppError(EXECUTION_FAILED_CODE, EXECUTION_FAILED_MESSAGE) from exc
        finally:
            _reset_connection(connection)


def _reset_connection(connection: Connection) -> None:
    try:
        reset_analytics_identity(connection)
        connection.execute(text("SET SESSION max_execution_time = 0"))
    except SQLAlchemyError:
        # 清理失败说明连接状态不可信：作废它，而不是把带着别人身份
        # 的连接归还连接池。
        logger.warning("analytics connection reset failed; invalidating")
        connection.invalidate()


def _is_timeout(exc: DBAPIError) -> bool:
    orig = exc.orig
    return bool(orig is not None and orig.args and orig.args[0] == _QUERY_TIMEOUT_ERRNO)


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
