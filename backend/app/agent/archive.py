import re
from dataclasses import asdict

from sqlalchemy.orm import Session

from app.agent.citations import Citation
from app.db.models import ConversationArchive, Customer

_ID_NUMBER_PATTERN = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
_BANK_CARD_PATTERN = re.compile(r"(?<!\d)(\d{16,19})(?!\d)")
_PHONE_PATTERN = re.compile(r"(?<!\d)(1\d{10})(?!\d)")


def _mask(value: str, *, keep_prefix: int, keep_suffix: int) -> str:
    stars = "*" * (len(value) - keep_prefix - keep_suffix)
    return f"{value[:keep_prefix]}{stars}{value[len(value) - keep_suffix:]}"


def _mask_id_number(match: re.Match[str]) -> str:
    # 18 位数字身份证号与 18 位银行卡号在字符形态上无法区分，此处按身份证号处理
    # （保留地区码），因此一个恰好 18 位的银行卡号会比 16/19 位银行卡号多暴露
    # 中间的地区码位——脱敏文本没有字段语义可供消歧，这是可接受的折衷。
    return _mask(match.group(1), keep_prefix=6, keep_suffix=4)


def _mask_bank_card(match: re.Match[str]) -> str:
    return _mask(match.group(1), keep_prefix=0, keep_suffix=4)


def _mask_phone(match: re.Match[str]) -> str:
    return _mask(match.group(1), keep_prefix=3, keep_suffix=4)


def _mask_name(name: str) -> str:
    if len(name) <= 1:
        return "*"
    return f"{name[0]}{'*' * (len(name) - 1)}"


def mask_pii(text: str, *, real_name: str | None = None) -> str:
    masked = text
    if real_name:
        masked = masked.replace(real_name, _mask_name(real_name))
    masked = _ID_NUMBER_PATTERN.sub(_mask_id_number, masked)
    masked = _BANK_CARD_PATTERN.sub(_mask_bank_card, masked)
    masked = _PHONE_PATTERN.sub(_mask_phone, masked)
    return masked


def record_turn(
    db: Session,
    *,
    session_id: str,
    user_id: int,
    agent_type: str,
    question: str,
    answer: str,
    citations: list[Citation],
    tool_calls: list[dict],
    content_classification: str,
) -> None:
    customer = db.get(Customer, user_id)
    real_name = customer.real_name if customer else None

    db.add(
        ConversationArchive(
            session_id=session_id,
            identity_domain="customer",
            user_id=user_id,
            agent_type=agent_type,
            role="user",
            content=mask_pii(question, real_name=real_name),
        )
    )
    db.add(
        ConversationArchive(
            session_id=session_id,
            identity_domain="customer",
            user_id=user_id,
            agent_type=agent_type,
            role="assistant",
            content=mask_pii(answer, real_name=real_name),
            tool_calls=tool_calls or None,
            citations=[asdict(citation) for citation in citations] or None,
            content_classification=content_classification,
        )
    )
    db.commit()
