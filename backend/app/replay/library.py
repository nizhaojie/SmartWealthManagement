"""预置演示数据：七类场景的确定性问答（ADR-0008）。

这里是回放模式的全部「剧本」，只存数据、不 import 任何应用模块——各缝
（``app.llm.provider``、``app.knowledge.service``、``app.agent.graph``、
``app.analytics``）自己来取并转换成各自的类型，避免双向依赖。

写作口径（这份数据会在评委面前被逐字看到，敷衍就在这里露馅）：

- 客服预置的分块内容**逐字摘自** ``app/knowledge/fixtures/faq_seed.md``，
  引用指向的是真实存在的知识，哪怕换一台机器演示也说得出来源；
- 回答是写给客户读的完整段落，编号标注 ``[N]`` 与 ``cited`` 一一对应，
  经 ``build_citations`` 校验后成为可点击角标；
- 涉及具体数字的图谱段落按基础种子数据（``app.db.seed``）手写——F000003
  的直接底层为 大盘蓝筹 0.4 + 利率债 0.2，两者合计为分母即约 67% / 33%；
  预置只用**已披露的产品要素**，不预置任何一位客户的持仓：客户侧是客户身份域，
  图谱只认登录客户本人，而回放预置与登录身份无关；
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
    # 图谱在客服侧的预置：问题命中产品实体，图谱段落给出该产品底层资产的行业
    # 构成（数字对齐基础种子：F000003 直接底层为 大盘蓝筹 0.4 + 利率债 0.2，
    # 两者合计为分母，即约 67% / 33%）。客户→产品→行业的多跳展示落在内部端的
    # 客户关系图（回放场景六），这里的问答只用已披露的产品要素。
    #
    # 这里刻意**不预置涉及某位客户持仓的问答**：客服侧是客户身份域，图谱只认登录
    # 客户本人（见 `agent/graph.py` 的 only_customer_id 与 `knowledge_graph/entities.py`），
    # 而回放预置按问题确定性复现、与登录身份无关——预置一位客户的持仓，等于让任何
    # 客户都读到别人的数据（客户可见视图里只有本人的持仓）。产品要素是已披露的
    # 事实性内容，任何客户问都得到同一个答案，这才是回放该有的形态。
    ChatPreset(
        question="天璇混合基金主要投在哪些行业？",
        chunks=(
            _faq_chunk(
                0,
                "产品说明书在哪里查看",
                "每只产品的详情页面提供产品说明书的下载入口，其中包含风险等级、投向、费率与业绩比较基准等完整披露信息。",
                0.90,
            ),
            _faq_chunk(
                1,
                "产品的起投金额在哪里查看",
                "每只产品的详情页面会展示起投金额、风险等级、投向与业绩比较基准等已披露要素，购买前请仔细核对。",
                0.80,
            ),
        ),
        passages=(
            PresetPassage(
                content="产品「天璇混合基金」底层资产中「大盘蓝筹」行业占比约67%。",
                entity_type="product",
                entity_value="天璇混合基金",
                tool="product_industries",
            ),
            PresetPassage(
                content="产品「天璇混合基金」底层资产中「利率债」行业占比约33%。",
                entity_type="product",
                entity_value="天璇混合基金",
                tool="product_industries",
            ),
        ),
        matched_entities=({"type": "product", "value": "天璇混合基金"},),
        # 行业构成来自图谱段落（融合后排在两个相似度分块之后，即 [3]、[4]）——
        # 论断挂的是它的实际来源；把图谱事实写成不带角标的话，客户点开角标只会
        # 看到知识库的问答，与回答里的数字对不上。角标按正文出现顺序排列，
        # `cited` 与正文一一对应（引用列表的顺序由正文角标决定）。
        answer=(
            "天璇混合基金的投向属于已披露的产品要素：产品说明书与产品详情页里"
            "都会给出风险等级、投向、费率与业绩比较基准等完整披露信息，可以在"
            "产品详情页查看并在购买前核对[1][2]。从底层资产的行业构成看，该产品"
            "约 67% 投向「大盘蓝筹」行业，其余约 33% 投向「利率债」行业[3][4]。"
        ),
        cited=(1, 2, 3, 4),
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
