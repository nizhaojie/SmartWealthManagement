from pydantic import BaseModel


class OperationAdviceRequest(BaseModel):
    # 客户经理选定的场景就是方向：这次建议是申购还是赎回。产品、金额与理由由
    # 业务操作 Agent 在候选池内给出——合法值在服务里判定，与投顾助手的侧重同一口径。
    direction: str


class OperationAdviceRejectRequest(BaseModel):
    # 驳回理由必填——顾问审的就是这份原稿；空串在这里放过，由服务判定并回明确文案。
    reason: str | None = None


class OperationAdviceCommentRequest(BaseModel):
    # 审核页的留言，与方案那一侧同一个口径：空串在这里放过，由服务判定并回明确文案。
    body: str | None = None


class CustomerDecisionRequest(BaseModel):
    # 客户的接受或拒绝；合法值在服务里判定（未知的取值一律回 400）。
    decision: str
