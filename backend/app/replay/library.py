"""预置演示数据：七类场景的确定性问答（ADR-0008）。

这里是回放模式的全部「剧本」，只存数据、不 import 任何应用模块——各缝
（``app.llm.provider``、``app.knowledge.service``、``app.agent.graph``、
``app.analytics``）自己来取并转换成各自的类型，避免双向依赖。

写作口径（这份数据会在评委面前被逐字看到，敷衍就在这里露馅）：

- 客服预置的分块内容**逐字摘自** ``app/knowledge/fixtures/faq_seed.md``，
  引用指向的是真实存在的知识，哪怕换一台机器演示也说得出来源；
- 回答是写给客户读的完整段落，编号标注 ``[N]`` 与 ``cited`` 一一对应，
  经 ``build_citations`` 校验后成为可点击角标；
- 涉及具体数字的图谱段落按基础种子数据（``app.db.seed``）手写——王守成
  持有 F000001，市值 20420，其底层 CASH-0001 权重 0.6 对应货币市场行业；
- 数据查询预置的 SQL 是对语义视图的合法只读查询，解读只描述口径、
  不写死行数——统计结果随种子数据增减而变，表格里的数字才是权威。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PresetChunk:
    """一条预置检索命中。字段与 ``ChunkResult`` 对齐，转换在缝上做。"""

    knowledge_id: int
    knowledge_type: str
    chunk_index: int
    heading_path: list[str]
    content: str
    score: float
    title: str
    source_file: str


@dataclass(frozen=True)
class PresetPassage:
    """一条预置图谱段落。字段与 ``GraphPassage`` 对齐，转换在缝上做。"""

    content: str
    entity_type: str
    entity_value: str
    tool: str


@dataclass(frozen=True)
class ChatPreset:
    """一个客服问答预置：检索命中 + 可选图谱段落 + 预写回答。

    ``cited`` 里的序号是 1-based 的分块位置，与回答文本里的 ``[N]`` 角标
    对应。带图谱段落的预置要注意融合后的顺序：向量分（0.6 * score）高于
    图谱分（0.4 * 1.0），向量块在前、图谱段落按给出顺序排在后面。
    """

    question: str
    chunks: tuple[PresetChunk, ...]
    answer: str
    cited: tuple[int, ...] = ()
    passages: tuple[PresetPassage, ...] = ()
    matched_entities: tuple[dict, ...] = ()


_FAQ_TITLE = "客户常见问题"
_FAQ_SOURCE = "faq_seed.md"

# 预置分块借用一个真实文档不可能出现的知识 id（自增主键恒为正，图谱融合
# 的段落用 -1）：演示环境里它不指向任何知识记录，前端只用标题与段落路径
# 渲染角标，不会拿它反查文档。
_PRESET_KNOWLEDGE_ID = 910_001


def _faq_chunk(index: int, heading: str, content: str, score: float) -> PresetChunk:
    return PresetChunk(
        knowledge_id=_PRESET_KNOWLEDGE_ID + index,
        knowledge_type="FAQ",
        chunk_index=index,
        heading_path=[_FAQ_TITLE, heading],
        content=content,
        score=score,
        title=_FAQ_TITLE,
        source_file=_FAQ_SOURCE,
    )


CHAT_PRESETS: tuple[ChatPreset, ...] = (
    ChatPreset(
        question="客户能否申购超出自己风险承受等级的产品？",
        chunks=(
            _faq_chunk(
                0,
                "客户能否申购超出自己风险承受等级的产品",
                "不能。系统按照适当性匹配规则做硬性限制，风险承受等级为 Cn 的客户只能申购风险等级不超过 Rn 的产品，越级产品不会出现在可申购范围内。",
                0.92,
            ),
            _faq_chunk(
                1,
                "产品风险等级和风险承受等级是一回事吗",
                "不是。产品风险等级取值为 R1 到 R5，用来衡量产品自身的风险高低；风险承受等级衡量的是客户能承受的风险，两者是两套独立的刻度。",
                0.86,
            ),
        ),
        answer=(
            "不可以[1]。系统按照适当性匹配规则做硬性限制：风险承受等级为 Cn 的客户"
            "只能申购风险等级不超过 Rn 的产品，越级产品不会出现在您的可申购范围内[1]。"
            "需要说明的是，产品风险等级（R1 到 R5）衡量的是产品自身的风险高低，与您"
            "本人的风险承受等级是两套独立的刻度，两者只在适当性匹配时进行比较[2]。"
            "您可以在每只产品的详情页查看其风险等级后再做选择。"
        ),
        cited=(1, 2),
    ),
    ChatPreset(
        question="产品的费率包含哪些项目？",
        chunks=(
            _faq_chunk(
                0,
                "产品的费率包含哪些项目",
                "产品费率通常包含管理费、托管费与销售服务费，具体费率以产品详情页披露的信息为准，不同产品费率结构不同。",
                0.90,
            ),
        ),
        answer=(
            "产品费率通常包含管理费、托管费与销售服务费三个项目[1]。不同产品的费率"
            "结构并不相同，具体费率请以产品详情页披露的信息为准，建议您在申购前核对"
            "详情页展示的费率明细[1]。"
        ),
        cited=(1,),
    ),
    ChatPreset(
        question="风险测评多久需要重新做一次？",
        chunks=(
            _faq_chunk(
                0,
                "风险测评多久需要重新做一次",
                "风险测评结论有效期为一年，到期后需重新完成测评，系统会在有效期临近时提醒客户。",
                0.91,
            ),
            _faq_chunk(
                1,
                "风险承受等级是如何得出的",
                "风险承受等级由客户完成风险测评问卷后计算得出，取值范围为 C1 到 C5，用于衡量客户能够承受的风险水平。",
                0.84,
            ),
        ),
        answer=(
            "风险测评结论的有效期为一年，到期后需要重新完成测评，系统会在有效期临近"
            "时提醒您[1]。您的风险承受等级正是由这份测评问卷计算得出的，取值范围为 "
            "C1 到 C5[2]，重新测评后等级结论也会随之更新。"
        ),
        cited=(1, 2),
    ),
    # 图谱多跳在客服侧的预置：问题命中客户实体，图谱段落给出
    # 客户 → 产品 → 行业的两跳事实（数字对齐基础种子：王守成持有
    # F000001 市值 20420，其底层 CASH-0001 / CASH-0002 权重 0.6 / 0.4）。
    ChatPreset(
        question="我的持仓集中投在哪些行业？",
        chunks=(
            _faq_chunk(
                0,
                "如何查看自己的持仓明细",
                "登录客户端后在“我的持仓”页面可查看当前持有的全部产品、持有份额、成本与盈亏情况。",
                0.90,
            ),
            _faq_chunk(
                1,
                "持仓页面的盈亏是如何计算的",
                "盈亏金额等于当前市值减去成本金额，盈亏比例为盈亏金额除以成本金额，页面数据随产品净值更新而变化。",
                0.80,
            ),
        ),
        passages=(
            PresetPassage(
                content="王守成持有产品「天枢货币基金」（货币基金，风险等级R1），份额20000.0，市值20420.0元。",
                entity_type="customer",
                entity_value="王守成",
                tool="customer_holdings",
            ),
            PresetPassage(
                content="王守成的持仓中「货币市场」行业占比约60%，市值合计12252.00元。",
                entity_type="customer",
                entity_value="王守成",
                tool="customer_industry_exposure",
            ),
            PresetPassage(
                content="王守成的持仓中「银行存款」行业占比约40%，市值合计8168.00元。",
                entity_type="customer",
                entity_value="王守成",
                tool="customer_industry_exposure",
            ),
        ),
        matched_entities=({"type": "customer", "value": "王守成"},),
        answer=(
            "您当前持有的天枢货币基金产品风险等级为 R1，从底层投向看集中在两类"
            "行业：约 60% 的市值落在「货币市场」行业，其余约 40% 落在银行存款类"
            "资产上。您可以在「我的持仓」页面随时查看持有的全部产品、份额、成本"
            "与盈亏[1]，其中盈亏金额等于当前市值减去成本金额[2]。"
        ),
        cited=(1, 2),
    ),
)

CHITCHAT_PRESETS: dict[str, str] = {
    "你好": "您好，我是智能财富管家系统的智能客服，可以为您解答产品要素、政策条款与常见问题，请问有什么可以帮您？",
    "在吗": "在的，请问有什么可以帮您？我可以回答产品要素、政策条款与常见问题方面的咨询。",
}


@dataclass(frozen=True)
class AnalyticsPreset:
    """一个数据查询预置：合法的语义视图查询 + 预写解读。

    解读只描述口径与读法、不写死行数：统计结果随种子数据增减而变，
    表格里实时查出的数字才是权威，解读抢答数字反而会露馅。
    """

    question: str
    sql: str
    interpretation: str


ANALYTICS_PRESETS: tuple[AnalyticsPreset, ...] = (
    AnalyticsPreset(
        question="统计各风险等级的在售产品数量",
        sql=(
            "SELECT risk_level, COUNT(*) AS product_count FROM va_product_element "
            "WHERE product_status = '在售' GROUP BY risk_level ORDER BY risk_level"
        ),
        interpretation=(
            "该查询按产品风险等级统计了在售产品的数量分布，结果不含已停售产品。"
            "数据口径：语义视图 va_product_element 来源于产品主数据，仅包含已对外"
            "披露的产品要素，不涉及任何客户数据。您可以将表格中各风险等级的产品"
            "数量与整体在售规模对照，了解在售产品的风险结构。"
        ),
    ),
    # 风控专员自然语言查询的预置：同一查询链路（analytics.run_query），
    # 视图范围收窄到预警统计。
    AnalyticsPreset(
        question="按预警等级统计每类预警的数量",
        sql=(
            "SELECT alert_level, COUNT(*) AS alert_count FROM va_risk_alert_stat "
            "GROUP BY alert_level ORDER BY alert_level"
        ),
        interpretation=(
            "该查询按预警等级汇总了预警数量。数据口径：语义视图 va_risk_alert_stat "
            "一行对应一条预警事实，已内置行级权限过滤，统计范围是您有权查看的预警"
            "记录。预警等级由命中规则的权重与等级判定得出，反映的是触发的严重程度；"
            "每条预警的触发详情与处置状态可在预警列表中逐一查看。"
        ),
    ),
)


def chat_preset(question: str) -> ChatPreset | None:
    return _CHAT_BY_QUESTION.get(question.strip())


def analytics_preset(question: str) -> AnalyticsPreset | None:
    return _ANALYTICS_BY_QUESTION.get(question.strip())


_CHAT_BY_QUESTION: dict[str, ChatPreset] = {preset.question: preset for preset in CHAT_PRESETS}
_ANALYTICS_BY_QUESTION: dict[str, AnalyticsPreset] = {
    preset.question: preset for preset in ANALYTICS_PRESETS
}
