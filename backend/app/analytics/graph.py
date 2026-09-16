"""数据分析 Agent 的查询链路：选视图 → 生成 → 校验 → 执行。

ADR-0007：与智能客服共用一套 LangGraph 运行时。链路是线性的；任一环节
失败把业务错误码写进 state 并短路到 END，由 service 层统一留痕并抛出
——这样被拒绝的尝试也能留下包含所生成查询的完整记录。结果解读与短期
记忆在 ticket 03 进入链路，届时 Agent 配置（提示词、记忆策略、内容分类
默认值）随之补全。
"""

from typing import TypedDict

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.analytics import catalog, execution, llm, validation
from app.analytics import examples as query_examples
from app.analytics.errors import OUT_OF_SCOPE_CODE, OUT_OF_SCOPE_MESSAGE
from app.analytics.examples import QueryExample
from app.db.models import Employee
from app.exceptions import AppError
from app.settings import Settings


class AnalyticsState(TypedDict, total=False):
    question: str
    views: list[catalog.ViewSpec]
    view_definitions: str
    examples: list[QueryExample]
    sql: str
    result: execution.QueryResult
    error_code: int
    error_message: str


def build_graph(db: Session, settings: Settings, *, employee: Employee):
    graph = StateGraph(AnalyticsState)

    def select_views_node(state: AnalyticsState) -> dict:
        views = catalog.select_views(state["question"])
        if not views:
            return {
                "error_code": OUT_OF_SCOPE_CODE,
                "error_message": OUT_OF_SCOPE_MESSAGE,
            }
        all_examples = query_examples.load_examples(settings)
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
                employee_id=employee.id,
                role=employee.employee_role,
                settings=settings,
            )
        except AppError as exc:
            return {"error_code": exc.code, "error_message": exc.message}
        return {"result": result}

    graph.add_node("select_views", select_views_node)
    graph.add_node("generate_query", generate_node)
    graph.add_node("validate_query", validate_node)
    graph.add_node("execute_query", execute_node)

    graph.set_entry_point("select_views")

    def route_or_end(next_node: str):
        def route(state: AnalyticsState) -> str:
            return END if "error_code" in state else next_node

        return route

    graph.add_conditional_edges("select_views", route_or_end("generate_query"))
    graph.add_conditional_edges("generate_query", route_or_end("validate_query"))
    graph.add_conditional_edges("validate_query", route_or_end("execute_query"))
    graph.add_edge("execute_query", END)

    return graph.compile()
