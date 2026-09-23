"""操作建议在客户侧的生命周期：送达之后的读取与客户决定。

一条已放行的操作建议在客户侧有四种状态（CONTEXT「客户决定」）：

    待客户决定 → 已接受 / 已拒绝 / 已过期

三个终态都是**事实陈述**，不是流程节点，因此这里没有一张状态表：

- 已接受 / 已拒绝来自一条客户决定记录（谁、什么时候、对哪条建议、接受还是拒绝）；
- 已过期是时间的事实——送达满 **7 个自然日**而客户没有作答。它不落库：落一个「已过期」
  字段就要有人去改它，而改它没有任何触发点。

**送达时间取放行那一刻的审核留痕**：放行是一次理财顾问的决定，
`biz_advisory_review_audit` 记着谁在什么时候放行的。操作建议放行不产生第二份载荷
（**#06**），审核记录上的「已放行」本身就是送达依据，因此放行时间从留痕里读，不在
别处再存一份。

**未放行的建议在客户侧一律读不到**：这里是「未经审核不可送达」这条护栏的第二个出口，
读取入口按「已放行」过滤，而不是靠调用方记得加条件；别人的建议与不存在的建议同义，
都回 404——不确认他人资源是否存在。

**接受是一次原子操作**：先写客户决定，再走与直接交易**同一套**受理服务
（`app.order_acceptance`：适当性、余额、起投金额、产品状态、赎回份额）。受理的提交
（`submit_transaction_event`）会把这条决定一起提交，于是「接受」与「成交」同时发生或
同时不发生；校验不过时回滚，建议留在待客户决定——客户补足余额后可以再来一次，
不存在「已接受但成交失败」这个状态。

赎回建议带一个**发起人选定的份额**（ADR-0021），接受时按它成交：受理侧的份额校验会
重新跑一遍，客户自己动过持仓导致份额不足就是接受失败，不会静默地按当下的全部持仓成交。
份额列为空表示「全部赎回」——那是改动之前落库的行（当时只存金额），它按接受那一刻的
全部持仓成交（`_redemption_shares` 的回退分支），旧语义因此原样延续。

**「我的建议」是分页列表（ADR-0024）**，排序是「送达时间倒序 + 建议标识兜底」的全序键：
同一秒送达的两条若没有确定的先后，翻页会把一条读两次、另一条谁也读不到。切片与 `total`
都从同一个列表派生（`pagination.paginate`），因此越界页返回空 `items` 而 `total` 不变。
列表的 `status` 过滤与页面分组读的是同一个算出来的状态（`status_of`），不另立一套口径。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.advisory.pipeline import CONTENT_TYPE_OPERATION_ADVICE
from app.advisory.review_status import ACTION_RELEASE, STATUS_RELEASED
from app.agent.classification import disclaimer_for
from app.customer_assets.service import list_holding_shares
from app.db.models import (
    AdvisoryReview,
    AdvisoryReviewAudit,
    OperationAdviceDecision,
    OperationAdviceDraft,
    Product,
)
from app.event_bus import EventPublisher
from app.exceptions import AppError
from app.order_acceptance import service as order_acceptance
from app.pagination import PageParams, paginate

DECISION_ACCEPT = "接受"
DECISION_REJECT = "拒绝"
DECISIONS = (DECISION_ACCEPT, DECISION_REJECT)

STATUS_AWAITING = "待客户决定"
STATUS_ACCEPTED = "已接受"
STATUS_REJECTED = "已拒绝"
STATUS_EXPIRED = "已过期"

# 客户侧的全部状态：`status` 过滤只认这四个，别的一律拒绝，而不是「查不到就是空」——
# 一个拼错的状态会回一份空列表，而空列表在分页之前是「你还没有建议」的同一句话。
ADVICE_STATUSES = (STATUS_AWAITING, STATUS_ACCEPTED, STATUS_REJECTED, STATUS_EXPIRED)

# 有效期 7 个自然日：从送达那一刻起的自然日，不按工作日算（spec Q17）。
VALIDITY_DAYS = 7

ZERO = Decimal("0.00")

ADVICE_NOT_FOUND_MESSAGE = "操作建议不存在"
UNKNOWN_DECISION_MESSAGE = "未知的客户决定"
UNKNOWN_STATUS_MESSAGE = "未知的建议状态"
ALREADY_DECIDED_MESSAGE = "该建议已有客户决定"
EXPIRED_MESSAGE = "该建议已过期，不能再接受，请客户经理重新发起"
MISSING_RELEASED_AT_MESSAGE = "操作建议缺少放行留痕，无法判定有效期"

# 客户送达视图里保留的字段：建议本身的四件事（产品、方向、金额、理由）加上状态、时限与
# 决定结果。发起人（客户经理）、内容分类、客户标识都不在其中——它们不是客户要读的东西，
# 却会在导出、分享这类下一个出口上一起漏出去。逐项拣选而不是 `{**row}` 展开：以后往
# 建议里加字段时默认是内部字段，要让它送达客户必须在这里显式加一次（ADR-0016）。
CUSTOMER_VISIBLE_ADVICE_FIELDS = (
    "id",
    "product_code",
    "product_name",
    "direction",
    "amount",
    "reason",
    "status",
    "released_at",
    "expires_at",
    "decision",
    "decided_at",
    "disclaimer",
)


def expires_at(released_at: datetime) -> datetime:
    """这条建议的有效期截止时刻：送达时间 + 7 个自然日。"""
    return released_at + timedelta(days=VALIDITY_DAYS)


def status_of(*, decision: str | None, released_at: datetime, now: datetime) -> str:
    """建议在客户侧的状态：决定记录优先，其次看它有没有过期。

    决定一旦落下就是终态，不再受时间影响——过了有效期之后再看一条已接受的建议，
    它仍然是「已接受」，不是「已过期」。
    """
    if decision == DECISION_ACCEPT:
        return STATUS_ACCEPTED
    if decision == DECISION_REJECT:
        return STATUS_REJECTED
    if now >= expires_at(released_at):
        return STATUS_EXPIRED
    return STATUS_AWAITING


def released_at_by_review(db: Session, review_ids: list[int]) -> dict[int, datetime]:
    """审核记录 → 放行时刻，取自放行留痕（一次查完这批）。

    客户侧的读取与内部侧的进度表读的是同一份事实，因此这个查询是公开的：两处各写
    一份的话，「送达时间」迟早会有一处改口径，而那一处看起来仍然完全正常。
    """
    if not review_ids:
        return {}
    rows = db.execute(
        select(AdvisoryReviewAudit.review_id, AdvisoryReviewAudit.decided_at).where(
            AdvisoryReviewAudit.review_id.in_(review_ids),
            AdvisoryReviewAudit.action == ACTION_RELEASE,
        )
    ).all()
    return {review_id: decided_at for review_id, decided_at in rows}


def release_moment(review: AdvisoryReview, released: dict[int, datetime]) -> datetime:
    """这条**已放行**建议的送达时刻，取自放行留痕（`released_at_by_review` 的批量结果）。

    已放行却没有留痕时当场报错：`record_decision` 一次提交里同时写两者，这个状态产生
    不了。宁可报错，也不要静默地把一条读不出有效期的建议说成「还有效」——它看起来
    完全正常，只是永远不会过期。

    这条规则只有这一处：客户侧的单条读、客户侧的列表与内部侧的进度表三处都要它，各写
    一遍的话，某一次改动只要漏掉其中一处，漏掉的那一处就会开始撒谎。
    """
    moment = released.get(review.id)
    if moment is None:
        raise AppError(500, MISSING_RELEASED_AT_MESSAGE)
    return moment


def optional_release_moment(
    review: AdvisoryReview, released: dict[int, datetime]
) -> datetime | None:
    """同一条规则，给「列表里混着未放行的建议」那一侧用：未放行就是 `None`（还没送达）。

    它与 `release_moment` 共用那条报错规则，因此「已放行必有留痕」不会在两处各写一遍。
    """
    if review.status != STATUS_RELEASED:
        return None
    return release_moment(review, released)


def _released_at(db: Session, review: AdvisoryReview) -> datetime:
    return release_moment(review, released_at_by_review(db, [review.id]))


def _delivered_statement(*, customer_id: int):
    """这位客户名下**已放行**的操作建议。

    过滤条只写在这一处：它是护栏 5 的第二个出口（未放行的建议在客户侧没有任何出口），
    列表读、单条读与决定三处共用同一条语句，谁也不会漏掉其中一条过滤——分开写的话，
    某一次改动漏掉 `status` 那一条就是一个不会报错的越权读。
    """
    return (
        select(AdvisoryReview, OperationAdviceDraft)
        .join(OperationAdviceDraft, OperationAdviceDraft.id == AdvisoryReview.content_ref)
        .where(
            AdvisoryReview.content_type == CONTENT_TYPE_OPERATION_ADVICE,
            AdvisoryReview.status == STATUS_RELEASED,
            OperationAdviceDraft.customer_id == customer_id,
        )
    )


def _delivered_reviews(
    db: Session, *, customer_id: int
) -> list[tuple[AdvisoryReview, OperationAdviceDraft]]:
    rows = db.execute(_delivered_statement(customer_id=customer_id)).all()
    return [(review, draft) for review, draft in rows]


def _delivered_advice(
    db: Session, *, advice_id: int, customer_id: int
) -> tuple[AdvisoryReview, OperationAdviceDraft]:
    row = db.execute(
        _delivered_statement(customer_id=customer_id).where(
            OperationAdviceDraft.id == advice_id
        )
    ).first()
    if row is None:
        # 未放行的、别人名下的与不存在的，在这里同义：客户侧读不到就是读不到。
        raise AppError(404, ADVICE_NOT_FOUND_MESSAGE)
    return row


def decisions_by_advice(
    db: Session, advice_ids: list[int]
) -> dict[int, OperationAdviceDecision]:
    """这批建议各自的客户决定（一次查完）。内部侧的进度表读的是同一批事实。"""
    if not advice_ids:
        return {}
    rows = db.scalars(
        select(OperationAdviceDecision).where(
            OperationAdviceDecision.advice_id.in_(advice_ids)
        )
    ).all()
    return {row.advice_id: row for row in rows}


def product_names(db: Session, product_codes: set[str]) -> dict[str, str | None]:
    """产品代码 → 名称。产品不在目录里只少一个名字，不让这条建议整行消失。"""
    if not product_codes:
        return {}
    rows = db.execute(
        select(Product.product_code, Product.product_name).where(
            Product.product_code.in_(product_codes)
        )
    ).all()
    return {code: name for code, name in rows}


def _serialize(
    *,
    draft: OperationAdviceDraft,
    product_name: str | None,
    released_at: datetime,
    decision: OperationAdviceDecision | None,
    now: datetime,
) -> dict:
    values = {
        "id": draft.id,
        "product_code": draft.product_code,
        "product_name": product_name,
        "direction": draft.direction,
        "amount": format(draft.amount, "f"),
        "reason": draft.reason,
        "status": status_of(
            decision=decision.decision if decision is not None else None,
            released_at=released_at,
            now=now,
        ),
        "released_at": released_at.isoformat(),
        "expires_at": expires_at(released_at).isoformat(),
        "decision": decision.decision if decision is not None else None,
        "decided_at": decision.decided_at.isoformat() if decision is not None else None,
        "disclaimer": disclaimer_for(draft.content_classification),
    }
    return {field: values[field] for field in CUSTOMER_VISIBLE_ADVICE_FIELDS}


def _serialize_one(
    db: Session,
    *,
    draft: OperationAdviceDraft,
    released_at: datetime,
    decision: OperationAdviceDecision | None,
    now: datetime,
) -> dict:
    return _serialize(
        draft=draft,
        product_name=product_names(db, {draft.product_code}).get(draft.product_code),
        released_at=released_at,
        decision=decision,
        now=now,
    )


def _delivered_items(db: Session, *, customer_id: int, now: datetime) -> list[dict]:
    """这位客户名下的**全部**已送达建议，按送达时间倒序排好。

    排完序才交给分页切片：只排当前页的话，「送达时间倒序」只在这一页内成立，翻页即乱
    （ADR-0024）。数据集因此是全集，`total` 与切片都由 `pagination.paginate` 从它派生。

    切片留在内存里做，是因为全序键（放行留痕上的送达时刻）与状态口径（现算）都在这一
    层：把排序下推到 SQL 就要把放行留痕连进来，把状态过滤下推就要把 `status_of` 再写
    一遍 SQL——而「同一个状态有两处口径」正是这批列表要挡住的形态。单客户的数据量是
    这一取舍成立的前提。
    """
    rows = _delivered_reviews(db, customer_id=customer_id)
    advice_ids = [draft.id for _review, draft in rows]
    decisions = decisions_by_advice(db, advice_ids)
    released = released_at_by_review(db, [review.id for review, _draft in rows])
    names = product_names(db, {draft.product_code for _review, draft in rows})

    items = []
    for review, draft in rows:
        items.append(
            _serialize(
                draft=draft,
                product_name=names.get(draft.product_code),
                released_at=release_moment(review, released),
                decision=decisions.get(draft.id),
                now=now,
            )
        )
    # 送达时刻相同时用建议标识兜底，同一个列表两次读出来才是确定的先后。这不是修辞：
    # 同一秒送达的两条若没有全序键，翻页会把一条读两次、另一条谁也读不到。
    items.sort(key=lambda item: (item["released_at"], item["id"]), reverse=True)
    return items


def list_my_advice(
    db: Session,
    *,
    customer_id: int,
    now: datetime,
    page: PageParams,
    status: str | None = None,
) -> dict:
    """本人的已送达建议的一页（送达时间倒序），以及过滤后的总数。

    待决定的与已决定的在同一个列表里：客户打开这一页要看的是「有哪些事在等我决定」，
    而回看已决定的不是另一个页面——分组由前端按状态现分，而不是分四份数据。

    `status` 是给侧栏角标用的：角标要的是「待决定共几条」，而列表本身是混合状态的，
    分页之后本页条数不再等于全局条数。它读的是同一个列表接口的过滤后 `total`，不另加
    一个 count 接口——两个口径迟早漂移，而「角标说 3、点进去是 2」正是提醒失效的形态。
    取值只认 `ADVICE_STATUSES`：拼错的状态静默回空列表，与「你还没有建议」是同一句话。

    「还没有建议」是空列表，不是 404——它不是一种错误。分页之后这一句只对 `total === 0`
    成立：越界的那一页也可以是空的。
    """
    items = _delivered_items(db, customer_id=customer_id, now=now)
    if status is not None:
        if status not in ADVICE_STATUSES:
            raise AppError(400, UNKNOWN_STATUS_MESSAGE)
        items = [item for item in items if item["status"] == status]
    return paginate(items, params=page)


def get_my_advice(db: Session, *, advice_id: int, customer_id: int, now: datetime) -> dict:
    review, draft = _delivered_advice(
        db, advice_id=advice_id, customer_id=customer_id
    )
    return _serialize_one(
        db,
        draft=draft,
        released_at=_released_at(db, review),
        decision=decisions_by_advice(db, [draft.id]).get(draft.id),
        now=now,
    )


def _current_holding_shares(db: Session, *, draft: OperationAdviceDraft) -> Decimal:
    """接受那一刻的持仓份额——**只**服务份额列为空的历史行（「空 = 全部赎回」）。"""
    return list_holding_shares(db, customer_id=draft.customer_id).get(
        draft.product_code, ZERO
    )


def _redemption_shares(db: Session, *, draft: OperationAdviceDraft) -> Decimal:
    """这次赎回的份额：发起人选定并存进草案的那一个。

    份额列为空表示「全部赎回」——那是改动之前落库的行（当时只存金额，成交用的是接受
    那一刻的全部持仓）。空值在这里被读成「当下的全部持仓」，旧语义因此原样延续；新写入
    的赎回建议一律带份额，不会走到这条回退分支。
    """
    if draft.redeemed_shares is not None:
        return draft.redeemed_shares
    return _current_holding_shares(db, draft=draft)


def _accept(
    db: Session,
    publisher: EventPublisher,
    *,
    draft: OperationAdviceDraft,
    now: datetime,
) -> dict:
    """把这条建议喂给与直接交易同一个受理服务（ADR-0018）：校验、成交、过规则引擎。

    受理侧先校验后写库，因此校验没过时会话里什么也没留下；这里再显式回滚一次，是因为
    带着客户决定的那一行已经在会话里待提交了——不同时撤掉，就会留下一条
    「已接受但没有成交」的决定。
    """
    try:
        if draft.direction == order_acceptance.PURCHASE:
            return order_acceptance.purchase(
                db,
                publisher=publisher,
                customer_id=draft.customer_id,
                product_code=draft.product_code,
                amount=draft.amount,
                now=now,
            )
        return order_acceptance.redeem(
            db,
            publisher=publisher,
            customer_id=draft.customer_id,
            product_code=draft.product_code,
            shares=_redemption_shares(db, draft=draft),
            now=now,
        )
    except Exception:
        # 余额不足、越级、已停售、份额不足……接受失败：决定不落库，建议留在待客户决定。
        db.rollback()
        raise


def decide(
    db: Session,
    publisher: EventPublisher,
    *,
    advice_id: int,
    customer_id: int,
    decision: str,
    now: datetime,
) -> dict:
    """客户对一条已送达建议做出接受或拒绝；接受当场成交，拒绝只留一条记录。"""
    if decision not in DECISIONS:
        raise AppError(400, UNKNOWN_DECISION_MESSAGE)

    review, draft = _delivered_advice(db, advice_id=advice_id, customer_id=customer_id)
    released_at = _released_at(db, review)
    if decisions_by_advice(db, [draft.id]).get(draft.id) is not None:
        raise AppError(409, ALREADY_DECIDED_MESSAGE)
    if now >= expires_at(released_at):
        # 过期即终态：接受与拒绝都不再受理——建议已经失效，再记一个决定没有意义。
        raise AppError(409, EXPIRED_MESSAGE)

    row = OperationAdviceDecision(
        advice_id=draft.id,
        customer_id=customer_id,
        decision=decision,
        decided_at=now,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        # 先读后写之间的并发：唯一约束在这里兜底，落成业务错误而不是 500。
        db.rollback()
        raise AppError(409, ALREADY_DECIDED_MESSAGE) from exc

    if decision == DECISION_REJECT:
        db.commit()
        db.refresh(row)
        return _serialize_one(
            db, draft=draft, released_at=released_at, decision=row, now=now
        )

    trade = _accept(db, publisher, draft=draft, now=now)
    # 受理的提交（`submit_transaction_event`）已经把上面那一行一起提交：接受与成交同时成立。
    db.refresh(row)
    payload = _serialize_one(
        db, draft=draft, released_at=released_at, decision=row, now=now
    )
    payload["transaction"] = trade["transaction"]
    payload["available_balance"] = trade["available_balance"]
    return payload
