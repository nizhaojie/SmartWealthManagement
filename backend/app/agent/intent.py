from enum import Enum


class Intent(str, Enum):
    PRODUCT = "产品咨询"
    POLICY = "政策解读"
    FAQ = "FAQ"
    CHITCHAT = "闲聊"
    HANDOFF = "转人工"
    # 客户在问自己名下的数据（持仓、流水、余额、风险等级、按等级筛产品）。
    # 它不进知识检索：由客服图确定性路由到复用的分析链路（ADR-0025）。
    DATA_QUERY = "数据查询"


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

# 数据查询的关键词刻意收窄到「指向本人数据」的那些说法：误判的代价是双向的——
# 一条产品要素问题被当成数据查询，客户拿到的是「查不到」而不是知识库里的说明书；
# 反过来，一条数据问题落到知识检索，客户拿到的是没有出处的泛泛之谈（比说查不到
# 更坏）。因此宁可用「我持有」「我的持仓」这类第一人称短语，不用「持有」「产品」
# 这类会与产品咨询重合的单词。
_DATA_QUERY_KEYWORDS = (
    # 第一人称 + 数据对象：问的是自己的账
    "我持有",
    "我买",
    "我的持仓",
    "我的产品",
    "我的余额",
    "我的资金",
    "我的账户",
    "我的交易",
    "我的流水",
    "我的风险",
    "我的画像",
    "我的标签",
    "适合我",
    # 资金流动的问法：上一轮已经在问自己的数据，追问（「这个月转了多少」）常常
    # 不再重复「我的」，靠的是同一件事的另一种说法。裸的「转账」「充值」不在此列：
    # 「转账限额是多少」问的是规则，不是数据。
    "转了多少",
    "充了多少",
    "充了",
    "入金",
    "流水",
    "交易记录",
    "持仓明细",
)


def classify_intent(question: str) -> Intent:
    if any(keyword in question for keyword in _HANDOFF_KEYWORDS):
        return Intent.HANDOFF
    if any(keyword in question for keyword in _DATA_QUERY_KEYWORDS):
        return Intent.DATA_QUERY
    # 金融关键词优先于闲聊关键词判断，避免「你好，请问……」这类带寒暄前缀的
    # 真实业务问题被误判为闲聊。
    if any(keyword in question for keyword in _POLICY_KEYWORDS):
        return Intent.POLICY
    if any(keyword in question for keyword in _PRODUCT_KEYWORDS):
        return Intent.PRODUCT
    if any(keyword in question for keyword in _CHITCHAT_KEYWORDS):
        return Intent.CHITCHAT
    return Intent.FAQ
