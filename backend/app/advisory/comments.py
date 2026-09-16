"""审核页留言：顾问与客户经理之间的沟通留痕，不是审核决定本身。

放行/驳回仍然只经 app.advisory.review 写入 AdvisoryReviewAudit；这里的
留言删了也不影响审核记录的完整性，纯粹是协作用的边车表。
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AdvisoryReviewComment, Employee
from app.exceptions import AppError

COMMENT_REQUIRED_MESSAGE = "留言内容不能为空"


def list_comments(db: Session, review_id: int) -> list[dict]:
    rows = db.scalars(
        select(AdvisoryReviewComment)
        .where(AdvisoryReviewComment.review_id == review_id)
        .order_by(AdvisoryReviewComment.created_at.asc())
    ).all()
    return [_serialize(db, row) for row in rows]


def add_comment(
    db: Session, review_id: int, *, author: Employee, body: str | None, now: datetime
) -> dict:
    if not (body and body.strip()):
        raise AppError(400, COMMENT_REQUIRED_MESSAGE)

    comment = AdvisoryReviewComment(
        review_id=review_id,
        author_id=author.id,
        author_role=author.employee_role,
        body=body.strip(),
        created_at=now,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return _serialize(db, comment)


def _serialize(db: Session, comment: AdvisoryReviewComment) -> dict:
    author = db.get(Employee, comment.author_id)
    return {
        "id": comment.id,
        "review_id": comment.review_id,
        "author_id": comment.author_id,
        "author_name": author.real_name if author else None,
        "author_role": comment.author_role,
        "body": comment.body,
        "created_at": comment.created_at.isoformat(),
    }
