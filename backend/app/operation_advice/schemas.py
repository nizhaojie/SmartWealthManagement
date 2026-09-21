from pydantic import BaseModel


class OperationAdviceRequest(BaseModel):
    # 客户经理选定的场景就是方向：这次建议是申购还是赎回。产品、金额与理由由
    # 业务操作 Agent 在候选池内给出——合法值在服务里判定，与投顾助手的侧重同一口径。
    direction: str
