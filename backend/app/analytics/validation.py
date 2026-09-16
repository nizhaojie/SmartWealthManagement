"""执行前校验：只允许单条 SELECT（ADR-0010 的第二道防线）。

第一道防线是结构性的——受限执行账号对基础表无权限、敏感字段不在
视图里；本模块是第二道，不是唯一防线：

- 写类操作与结构变更一律拒绝（删除、更新、插入、结构变更、清空等）；
- 只允许单条 SELECT：SET、多语句、注释拼接一律拒绝。行级权限依赖此
  前提——执行账号自身能 ``SET @analytics_employee_role`` 提权，必须
  保证模型生成的语句到不了 SET；``SELECT @var := ...`` 与
  ``SELECT ... INTO @var`` 是同一个提权面，一并拒绝。

刻意不做完整 SQL 解析：字符串字面量里的 ``--``、``;`` 也会被拒绝。
这是 fail-safe 的误伤——宁可误拒一条合法查询，不可放过一条拼接。
"""

import re

from app.analytics.errors import QUERY_REJECTED_CODE, QUERY_REJECTED_MESSAGE
from app.exceptions import AppError

_FORBIDDEN_KEYWORDS = frozenset(
    {
        # 写类操作
        "INSERT",
        "UPDATE",
        "DELETE",
        "REPLACE",
        # 结构变更
        "CREATE",
        "ALTER",
        "DROP",
        "TRUNCATE",
        "RENAME",
        # 会话状态与权限（行级权限的提权面）
        "SET",
        "GRANT",
        "REVOKE",
        # SELECT ... INTO OUTFILE 写文件 / INTO @var 写会话变量
        "INTO",
        # 其余非查询语句
        "CALL",
        "DO",
        "EXEC",
        "EXECUTE",
        "PREPARE",
        "DEALLOCATE",
        "LOCK",
        "UNLOCK",
        "HANDLER",
        "LOAD",
        "USE",
    }
)

_COMMENT_TOKENS = ("--", "#", "/*", "*/")
_WORD = re.compile(r"[A-Za-z_]+")
# 字符串字面量与反引号标识符先抹掉再做关键字扫描，避免 'delete' 这类
# 字面量或名为 `updated` 的列别名造成误伤。
_STRING_OR_IDENTIFIER = re.compile(
    r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.|\"\"])*\"|`[^`]*`"
)


def validate_query(sql: str) -> str:
    """校验通过则返回规整后的语句；任何一类违规都抛业务错误码。"""
    normalized = sql.strip()
    if not normalized:
        raise _reject("空查询")
    if any(token in normalized for token in _COMMENT_TOKENS):
        raise _reject("不允许注释")
    if ";" in normalized:
        raise _reject("只允许单条语句")
    if "@" in normalized:
        raise _reject("不允许会话变量")
    scrubbed = _STRING_OR_IDENTIFIER.sub(" ", normalized)
    words = [word.upper() for word in _WORD.findall(scrubbed)]
    if not words or words[0] != "SELECT":
        raise _reject("只允许 SELECT 语句")
    for word in words:
        if word in _FORBIDDEN_KEYWORDS:
            raise _reject(f"不允许的关键字 {word}")
    return normalized


def _reject(reason: str) -> AppError:
    return AppError(QUERY_REJECTED_CODE, f"{QUERY_REJECTED_MESSAGE}：{reason}")
