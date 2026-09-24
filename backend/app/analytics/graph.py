"""数据分析 Agent 的查询链路：选视图 → 生成 → 校验 → 执行 → 解读。

ADR-0007：与智能客服共用一套 LangGraph 运行时。链路是线性的；任一环节
失败把业务错误码写进 state 并短路到 END，由**调用方**决定怎么呈现——员工
路径（``service.run_query``）统一留痕并抛出，被拒绝的尝试因此也留下包含所
生成查询的完整记录；客服的数据查询分支把它转成面向客户的话术（ADR-0025）。
多轮追问的上一轮问题由调用方放进 ``history``：它既是生成的上下文，也进选
视图的语境（``select_views_node``）。
"""

from collections.abc import Collection
from typing import TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.analytics import catalog, execution, interpretation, llm, validation
from app.analytics import examples as query_examples
from app.analytics.audience import Audience
from app.analytics.errors import OUT_OF_SCOPE_CODE, OUT_OF_SCOPE_MESSAGE
from app.analytics.examples import QueryExample
from app.db.analytics_account import AnalyticsIdentity
from app.exceptions import AppError
from app.settings import Settings


class AnalyticsState(TypedDict, total=False):
    question: str
    history: list[dict]
    views: list[catalog.ViewSpec]
    view_definitions: str
    examples: list[QueryExample]
    sql: str
    result: execution.QueryResult
    interpretation: str
    error_code: int
    error_message: str


def build_graph(
    db: Session,
    settings: Settings,
    *,
    identity: AnalyticsIdentity,
    view_names: Collection[str] | None = None,
    audience: Audience = Audience.EMPLOYEE,
):
    """查询链路：选视图 → 生成 → 校验 → 执行 → 解读（ADR-0010）。

    ``view_names`` 限定这个 Agent 的视图范围，缺省时是目录内的全部视图。风控监测
    Agent 传入预警视图，于是超出风控域的问题在选视图一步就没有候选，直接判为
    「超出可查范围」——模型看不到也生成不出别的域的查询。语义视图分员工 / 客户
    两域（ADR-0025），调用方都显式传入自己那一域，两域因此互不可见。

    ``identity`` 决定查得到哪些行（执行时写进连接的会话变量），``audience`` 决定
    生成与解读面向谁说话。两者由同一个调用点给出，见 ``service.run_restricted_query``。
    """
    graph = StateGraph(AnalyticsState)

    def select_views_node(state: AnalyticsState) -> dict:
        # 多轮追问（「那上个季度呢」）本身可能不含任何视图关键词，
        # 上一轮的提问才是语境——选视图时把历史问题一并纳入匹配。
        context = state["question"] + "\n" + "\n".join(
            message["content"]
            for message in state.get("history", [])
            if message.get("role") == "user"
        )
        views = catalog.select_views(context, allowed=view_names)
        if not views:
            return {
                "error_code": OUT_OF_SCOPE_CODE,
                "error_message": OUT_OF_SCOPE_MESSAGE,
            }
        all_examples = query_examples.load_examples(settings)
        if view_names is not None:
            # 示例与视图一样分域：跨域示例（产品要素是两域共有的那一张视图）不得
            # 进提示词，否则员工侧会看到「怎么查客户自己的账」的样例，两域就互相
            # 看得见了。
            all_examples = query_examples.examples_within_view_names(
                all_examples, view_names
            )
        return {
            "views": views,
            "view_definitions": catalog.view_definitions(db, views),
            "examples": query_examples.examples_for_views(all_examples, views),
        }

    def generate_node(state: AnalyticsState) -> dict:
        try:
            sql = llm.generate_query(
                state["question"],
                [view.name for view in state["views"]],
                state["view_definitions"],
                state["examples"],
                settings,
                history=state.get("history", []),
                audience=audience,
            )
        except AppError as exc:
            return {"error_code": exc.code, "error_message": exc.message}
        return {"sql": sql}

    def validate_node(state: AnalyticsState) -> dict:
        try:
            sql = validation.validate_query(state["sql"])
        except AppError as exc:
            return {"error_code": exc.code, "error_message": exc.message}
        return {"sql": sql}

    def execute_node(state: AnalyticsState) -> dict:
        try:
            result = execution.execute_query(
                execution.base_url_of(db),
                state["sql"],
                identity=identity,
                settings=settings,
            )
        except AppError as exc:
            return {"error_code": exc.code, "error_message": exc.message}
        return {"result": result}

    def interpret_node(state: AnalyticsState) -> dict:
        text = interpretation.generate_interpretation(
            state["question"],
            state["views"],
            state["result"],
            settings,
            audience=audience,
        )
        return {"interpretation": text}

    graph.add_node("select_views", select_views_node)
    graph.add_node("generate_query", generate_node)
    graph.add_node("validate_query", validate_node)
    graph.add_node("execute_query", execute_node)
    graph.add_node("interpret_result", interpret_node)

    graph.set_entry_point("select_views")

    def route_or_end(next_node: str):
        def route(state: AnalyticsState) -> str:
            return END if "error_code" in state else next_node

        return route

    graph.add_conditional_edges("select_views", route_or_end("generate_query"))
    graph.add_conditional_edges("generate_query", route_or_end("validate_query"))
    graph.add_conditional_edges("validate_query", route_or_end("execute_query"))
    graph.add_conditional_edges("execute_query", route_or_end("interpret_result"))
    graph.add_edge("interpret_result", END)

    return graph.compile()
