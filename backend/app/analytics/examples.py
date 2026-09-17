"""「问题 → 查询」示例：提升生成准确率的少量样例，可配置而不必改代码。

默认读取随仓库提供的 ``query_examples.json``；``analytics_examples_path``
指向另一个 JSON 文件即可整体替换。示例按视图过滤——只注入与当前问题
相关视图的示例，避免提示词膨胀。
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


def examples_for_view_names(
    examples: tuple[QueryExample, ...], view_names: Iterable[str]
) -> list[QueryExample]:
    """只保留与给定视图集合相交的示例；空集合时返回空（不给任何示例）。"""
    selected = set(view_names)
    return [example for example in examples if selected & set(example.views)]
