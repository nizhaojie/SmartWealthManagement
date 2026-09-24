"""「问题 → 查询」示例：提升生成准确率的少量样例，可配置而不必改代码。

默认读取随仓库提供的 ``query_examples.json``；``analytics_examples_path``
指向另一个 JSON 文件即可整体替换。示例按视图过滤——只注入与当前问题
相关视图的示例，避免提示词膨胀；再按 Agent 的视图范围收一次，两域的
示例因此与两域的视图一样互不可见（``examples_within_view_names``）。
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.analytics.catalog import ViewSpec
from app.settings import Settings

_DEFAULT_EXAMPLES_FILE = Path(__file__).resolve().parent / "query_examples.json"


@dataclass(frozen=True)
class QueryExample:
    question: str
    sql: str
    views: tuple[str, ...]


def load_examples(settings: Settings) -> tuple[QueryExample, ...]:
    path = settings.analytics_examples_path or str(_DEFAULT_EXAMPLES_FILE)
    return _load_examples(path)


@lru_cache(maxsize=None)
def _load_examples(path: str) -> tuple[QueryExample, ...]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    examples = []
    for item in raw:
        examples.append(
            QueryExample(
                question=str(item["question"]),
                sql=str(item["sql"]),
                views=tuple(str(view) for view in item["views"]),
            )
        )
    return tuple(examples)


def examples_for_views(
    examples: tuple[QueryExample, ...], views: list[ViewSpec]
) -> list[QueryExample]:
    return examples_for_view_names(examples, (view.name for view in views))


def examples_within_view_names(
    examples: tuple[QueryExample, ...], view_names: Iterable[str]
) -> tuple[QueryExample, ...]:
    """只保留视图面被候选集**完全覆盖**的示例（ADR-0025）。

    与 ``examples_for_view_names`` 的交集口径不同：这里要的是「这条示例不越域」。
    产品要素是员工侧与客户域共有的那一张视图，一条「客户拿自己的风险等级筛产品」
    的示例与员工候选集有交集，却带着客户域的视图——按交集放行就等于让员工侧的
    提示词里出现客户域的视图名。
    """
    allowed = set(view_names)
    return tuple(example for example in examples if set(example.views) <= allowed)


def examples_for_view_names(
    examples: tuple[QueryExample, ...], view_names: Iterable[str]
) -> list[QueryExample]:
    """只保留与给定视图集合相交的示例；空集合时返回空（不给任何示例）。"""
    selected = set(view_names)
    return [example for example in examples if selected & set(example.views)]
