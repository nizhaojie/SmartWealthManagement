from enum import Enum


class Intent(str, Enum):
    PRODUCT = "产品咨询"
    POLICY = "政策解读"
    FAQ = "FAQ"
    CHITCHAT = "闲聊"
    HANDOFF = "转人工"


RETRIEVAL_INTENTS = {Intent.PRODUCT, Intent.POLICY, Intent.FAQ}

_HANDOFF_KEYWORDS = ("转人工", "人工客服", "人工坐席", "找人工", "投诉", "换个人工", "转接人工")

_CHITCHAT_KEYWORDS = (
    "你好",
    "在吗",
    "你是谁",
    "讲个笑话",
    "天气",
    "吃了吗",
    "谢谢",
    "拜拜",
    "再见",
    "无聊",
    "聊聊天",
    "你叫什么",
)

_POLICY_KEYWORDS = ("政策", "规定", "条款", "法规", "细则", "办法")

_PRODUCT_KEYWORDS = ("产品", "费率", "净值", "起投", "赎回", "期限", "收益率", "份额")


def classify_intent(question: str) -> Intent:
    if any(keyword in question for keyword in _HANDOFF_KEYWORDS):
        return Intent.HANDOFF
    # 金融关键词优先于闲聊关键词判断，避免「你好，请问……」这类带寒暄前缀的
    # 真实业务问题被误判为闲聊。
    if any(keyword in question for keyword in _POLICY_KEYWORDS):
        return Intent.POLICY
    if any(keyword in question for keyword in _PRODUCT_KEYWORDS):
        return Intent.PRODUCT
    if any(keyword in question for keyword in _CHITCHAT_KEYWORDS):
        return Intent.CHITCHAT
    return Intent.FAQ
