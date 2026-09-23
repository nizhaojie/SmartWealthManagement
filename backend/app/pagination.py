"""列表接口的统一分页契约（ADR-0024）。

响应的 `data` 恒为 `{items, total, page, page_size}`，列表字段统一叫 `items`。
形状只有这一份定义：二十余个列表接口各写一遍的话，参数命名、响应形状与 `total`
口径必然漂移，而前端要靠同一个 `Paginated<T>` 泛型读它们。

`page` 从 1 起，`page_size` 默认 20、上限 100。上限是**钳制**而不是拒收：客户端的
页长越界是一个可以就地纠正的请求，为它返回 400 只会让翻页在数据变多时突然失效。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from fastapi import Depends, Query
from pydantic import BaseModel

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

ItemT = TypeVar("ItemT")


class PaginatedResponse(BaseModel, Generic[ItemT]):
    """列表接口 `data` 的统一形状：本页条目 + 过滤后总数 + 本页的页码与页长。"""

    items: list[ItemT]
    total: int
    page: int
    page_size: int


@dataclass(frozen=True)
class PageParams:
    """一次请求的分页窗口。`page`/`page_size` 的口径只有这一处。"""

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def page_params(
    page: int = Query(default=1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(
        default=DEFAULT_PAGE_SIZE, ge=1, description=f"每页条数，上限 {MAX_PAGE_SIZE}"
    ),
) -> PageParams:
    """分页参数的依赖：校验并钳制，接口自己不碰这两个数字。

    列表接口一律写成 `page: PageParams = Depends(page_params)`——参数名、默认值与
    上限只有这一处，接口不再各写一遍 `page`/`page_size` 的声明。
    """
    return PageParams(page=page, page_size=min(page_size, MAX_PAGE_SIZE))


def paginate(items: Sequence[ItemT], *, params: PageParams) -> dict[str, Any]:
    """把**过滤之后的全量**列表切成当前页。

    传进来的必须是过滤后的全集而不是某一页：`total` 取它的长度，所以口径是「满足筛选
    条件的记录共有多少条」，与页码无关——越界页因此返回空 `items` 而 `total` 不变。
    内存里排序的列表（交易流水三表扇入）要先合并、排序、再交给这里切片，否则
    `total` 是全集而顺序只在页内成立。
    """
    window = list(items[params.offset : params.offset + params.page_size])
    return PaginatedResponse(
        items=window, total=len(items), page=params.page, page_size=params.page_size
    ).model_dump()
