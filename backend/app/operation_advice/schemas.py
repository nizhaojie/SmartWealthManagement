from decimal import Decimal

from pydantic import BaseModel


class OperationAdviceRequest(BaseModel):
    # 客户经理选定的场景就是方向：这次建议是申购还是赎回。产品与金额 / 份额同样由
    # 发起人给（ADR-0021），Agent 只产出理由。合法值在服务里判定，与投顾助手的侧重同一口径。
    direction: str
    product_code: str
    # 申购填金额、赎回填份额——与客户侧自助交易同一个口径（`api/customer_transactions`）。
    # 哪个必填由方向决定，因此两个字段在请求体的形状上都是可空的：判定与方向本身在
    # 同一处（服务端受理校验），形状上的必填表达不了这个条件。
    amount: Decimal | None = None
    shares: Decimal | None = None


class OperationAdviceRejectRequest(BaseModel):
    # 驳回理由必填——顾问审的就是这份原稿；空串在这里放过，由服务判定并回明确文案。
    reason: str | None = None


class OperationAdviceCommentRequest(BaseModel):
    # 审核页的留言，与方案那一侧同一个口径：空串在这里放过，由服务判定并回明确文案。
    body: str | None = None


class CustomerDecisionRequest(BaseModel):
    # 客户的接受或拒绝；合法值在服务里判定（未知的取值一律回 400）。
    decision: str
