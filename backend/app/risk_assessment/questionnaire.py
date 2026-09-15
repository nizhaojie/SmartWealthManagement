from dataclasses import dataclass


@dataclass(frozen=True)
class Option:
    id: str
    label: str
    score: int


@dataclass(frozen=True)
class Question:
    id: str
    dimension: str
    prompt: str
    options: tuple[Option, ...]


INCOME = "收入"
EXPERIENCE = "投资经验"
TOLERANCE = "风险承受力"
GOAL = "投资目标"

QUESTIONS: tuple[Question, ...] = (
    Question(
        id="q01",
        dimension=INCOME,
        prompt="您目前的年收入大致处于哪个区间？",
        options=(
            Option("A", "10 万以下", 1),
            Option("B", "10 万（含）至 30 万", 2),
            Option("C", "30 万（含）至 50 万", 3),
            Option("D", "50 万及以上", 4),
        ),
    ),
    Question(
        id="q02",
        dimension=INCOME,
        prompt="未来三年，您预期自己的收入会如何变化？",
        options=(
            Option("A", "可能明显下降或很不稳定", 1),
            Option("B", "基本持平，略有波动", 2),
            Option("C", "稳步增长", 3),
            Option("D", "有较大增长空间", 4),
        ),
    ),
    Question(
        id="q03",
        dimension=INCOME,
        prompt="您家庭的主要收入来源是？",
        options=(
            Option("A", "社会保障或家庭资助", 1),
            Option("B", "工资薪金", 2),
            Option("C", "工资薪金加部分经营或投资所得", 3),
            Option("D", "经营所得或投资所得为主", 4),
        ),
    ),
    Question(
        id="q04",
        dimension=INCOME,
        prompt="扣除日常生活开销后，您每年可用于投资的资金大约占年收入的？",
        options=(
            Option("A", "10% 以下", 1),
            Option("B", "10%（含）至 20%", 2),
            Option("C", "20%（含）至 40%", 3),
            Option("D", "40% 及以上", 4),
        ),
    ),
    Question(
        id="q05",
        dimension=EXPERIENCE,
        prompt="您参与投资理财的时间大约有多久？",
        options=(
            Option("A", "不足 1 年或几乎没有", 1),
            Option("B", "1 年（含）至 3 年", 2),
            Option("C", "3 年（含）至 5 年", 3),
            Option("D", "5 年及以上", 4),
        ),
    ),
    Question(
        id="q06",
        dimension=EXPERIENCE,
        prompt="您曾经投资过哪些类型的产品？",
        options=(
            Option("A", "银行存款、货币基金等低波动产品", 1),
            Option("B", "还买过债券型或稳健型理财", 2),
            Option("C", "还买过混合型基金或银行理财", 3),
            Option("D", "还买过股票、股票型基金或衍生品", 4),
        ),
    ),
    Question(
        id="q07",
        dimension=EXPERIENCE,
        prompt="您对金融产品风险收益特征的了解程度是？",
        options=(
            Option("A", "不太了解，主要听他人介绍", 1),
            Option("B", "了解常见产品的基本特点", 2),
            Option("C", "能比较不同产品的风险与收益", 3),
            Option("D", "能独立分析产品结构并做出判断", 4),
        ),
    ),
    Question(
        id="q08",
        dimension=EXPERIENCE,
        prompt="过去五年，您参与过几次主动申购或赎回？",
        options=(
            Option("A", "几乎没有", 1),
            Option("B", "偶尔几次", 2),
            Option("C", "每年都会操作若干次", 3),
            Option("D", "交易较为频繁，已形成习惯", 4),
        ),
    ),
    Question(
        id="q09",
        dimension=TOLERANCE,
        prompt="如果持有的产品在半年内下跌 20%，您更可能怎么做？",
        options=(
            Option("A", "全部赎回，不能接受本金损失", 1),
            Option("B", "赎回一部分，降低后续波动", 2),
            Option("C", "继续持有，等待回升", 3),
            Option("D", "加仓，视作更好的买入机会", 4),
        ),
    ),
    Question(
        id="q10",
        dimension=TOLERANCE,
        prompt="您能接受的年度最大亏损大约是？",
        options=(
            Option("A", "几乎不能亏损", 1),
            Option("B", "不超过 5%", 2),
            Option("C", "不超过 15%", 3),
            Option("D", "可以超过 15%", 4),
        ),
    ),
    Question(
        id="q11",
        dimension=TOLERANCE,
        prompt="在同等预期收益下，您更看重哪一点？",
        options=(
            Option("A", "本金安全和可随时取出", 1),
            Option("B", "收益稳定、回撤可控", 2),
            Option("C", "收益与波动取得平衡", 3),
            Option("D", "尽量争取更高收益", 4),
        ),
    ),
    Question(
        id="q12",
        dimension=TOLERANCE,
        prompt="您对投资亏损的心理感受更接近哪一种？",
        options=(
            Option("A", "亏损会明显影响生活与情绪", 1),
            Option("B", "短期亏损可以接受，但会焦虑", 2),
            Option("C", "把波动视为投资的一部分", 3),
            Option("D", "更关注长期结果，短期亏损影响很小", 4),
        ),
    ),
    Question(
        id="q13",
        dimension=GOAL,
        prompt="您这笔资金最主要的投资目标是？",
        options=(
            Option("A", "保值，跑赢通胀即可", 1),
            Option("B", "稳健增值，兼顾流动性", 2),
            Option("C", "实现资产的中长期增长", 3),
            Option("D", "尽量提高长期收益率", 4),
        ),
    ),
    Question(
        id="q14",
        dimension=GOAL,
        prompt="您计划持有这笔投资的时间大约是？",
        options=(
            Option("A", "1 年以内", 1),
            Option("B", "1 年（含）至 3 年", 2),
            Option("C", "3 年（含）至 5 年", 3),
            Option("D", "5 年以上", 4),
        ),
    ),
    Question(
        id="q15",
        dimension=GOAL,
        prompt="这笔资金若暂时无法取出，对您日常生活的影响是？",
        options=(
            Option("A", "影响很大，随时可能要用", 1),
            Option("B", "会有些不便，但可以周转", 2),
            Option("C", "影响有限，预留了应急资金", 3),
            Option("D", "几乎没有影响，这是长期资金", 4),
        ),
    ),
    Question(
        id="q16",
        dimension=GOAL,
        prompt="您更希望投资组合呈现出怎样的收益特征？",
        options=(
            Option("A", "收益低但几乎不亏钱", 1),
            Option("B", "收益适中、波动较小", 2),
            Option("C", "收益与波动比较均衡", 3),
            Option("D", "收益尽量高，可以接受较大波动", 4),
        ),
    ),
)

QUESTION_BY_ID = {question.id: question for question in QUESTIONS}
OPTION_SCORE = {
    (question.id, option.id): option.score
    for question in QUESTIONS
    for option in question.options
}


def public_questions() -> list[dict]:
    return [
        {
            "id": question.id,
            "dimension": question.dimension,
            "prompt": question.prompt,
            "options": [{"id": option.id, "label": option.label} for option in question.options],
        }
        for question in QUESTIONS
    ]
