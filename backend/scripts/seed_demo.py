"""答辩演示数据：把库清成一套干净的最小可演示状态。

用法::

    cd backend
    python -m scripts.seed_demo                # 清库 + 重建 + 重建图谱
    python -m scripts.seed_demo --purge-only   # 只清，不重建
    python -m scripts.seed_demo --keep-graph   # 跳过知识图谱重建（Neo4j 没起时用）

**为什么不是 `python -m app.db.setup`。** setup 是幂等的「不存在才插入 + 回放」：
它能把余额对齐种子、把历史成交删掉重放，但**不删除任何一行多余的数据**。于是历次
演示、分页造数（`app.db.pagination_demo_seed`）与调试留下的行会一直躺在库里——
客户目录 52 人、在售产品 57 只、风评 1133 条——答辩现场一翻列表就能看见不属于
这个系统的数据。本脚本补的正是那一步：先清空，再交给同一个 `seed()` 重建。

**清到什么程度。**

清空（见 `_WIPE_TABLES`）：客户与画像、产品与底层资产、持仓、交易流水（申购赎回/
转账/充值）、风评与适当性判定、风控规则与规则调整留痕、预警、风险关注、工单与流转、
投顾内容（方案请求 / 原稿 / 审核 / 审核留痕 / 留言 / 定稿 / 操作建议原稿与客户决定）、
会话归档，以及三类工程留痕（调试级留痕、分析查询留痕、降级留痕、图谱重建记录）。

保留（见 `_KEEP_TABLES`）：`sys_employee`（四个演示账号，口令 `Test@1234`）、
知识库两张表（`fin_knowledge_meta` / `fin_knowledge_chunk`——知识语料与业务数据无关，
清掉要重新上传解析）、`alembic_version`。语义视图是视图，不在清空范围内。

知识库有它自己的清理命令：`python -m scripts.purge_knowledge`（只留正式语料的 10 篇，
连同 Milvus 向量与 MinIO 对象一起清）。两件事分开是因为知识库的权威副本在 Milvus、
原文在 MinIO，只清 MySQL 那一侧会留下孤儿向量与垃圾对象。

**重建的结果就是基础种子那一套**：5 位客户、7 只产品、10 个底层资产、20 条内置
风控规则，以及 5 笔历史成交逐笔回放产生的历史预警（走的是与实时交易同一个入海口，
不另写批量脚本）。风控规则之所以也一起清掉重建：种子只在表为空时播种（ADR-0027），
不清掉的话演示中被改过阈值或软删掉的规则不会回到内置的 20 条。

**知识图谱要跟着重建。** 图谱是 MySQL 的投影读模型（ADR-0002），客户与产品被清空
之后 Neo4j 里仍留着已经不存在的节点，图谱类回答会引用到查不到出处的数据。脚本默认
在重建种子之后做一次**全量重建**（幂等）；Neo4j 连不上时只告警不中断——MySQL 那一
侧的演示不受影响，只是图谱增强那部分会走降级路径。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.seed import seed
from app.settings import get_settings

# 清空：业务数据 + 工程留痕。顺序无关——清空前会关掉外键检查（`FOREIGN_KEY_CHECKS`），
# 而 TRUNCATE 把自增计数器也一起复位，重建出来的 id 从 1 开始。
_WIPE_TABLES: tuple[str, ...] = (
    # 客户与画像
    "sys_customer",
    "fin_customer_profile",
    "fin_profile_tag",
    "fin_profile_tag_conflict",
    # 产品与底层
    "fin_product",
    "fin_underlying_asset",
    "fin_product_underlying",
    # 资金与交易
    "fin_funding_account",
    "fin_transaction",
    "fin_transfer",
    "fin_deposit",
    "fin_holdings",
    # 风评与适当性
    "fin_risk_assessment",
    "fin_suitability_decision",
    # 风控
    "fin_risk_rule",
    "fin_risk_rule_change",
    "fin_risk_alert",
    "biz_risk_focus",
    "biz_work_order",
    "biz_work_order_transition",
    # 投顾内容
    "biz_advisory_request",
    "biz_advisory_draft",
    "biz_advisory_review",
    "biz_advisory_review_audit",
    "biz_advisory_review_comment",
    "biz_advisory_final",
    "biz_operation_advice_draft",
    "biz_operation_advice_decision",
    # 会话与留痕
    "conversation_archive",
    "agent_debug_trace",
    "biz_analytics_query_audit",
    "biz_degradation_trace",
    "biz_graph_sync_run",
)

# 保留：员工账号、知识库、迁移版本。这三样都不由重建负责。
_KEEP_TABLES: tuple[str, ...] = (
    "sys_employee",
    "fin_knowledge_meta",
    "fin_knowledge_chunk",
    "alembic_version",
)

# 汇报里按这个顺序打印行数，与演示时翻得到的那几屏一一对应。
_REPORT_TABLES: tuple[str, ...] = (
    "sys_employee",
    "sys_customer",
    "fin_product",
    "fin_underlying_asset",
    "fin_holdings",
    "fin_funding_account",
    "fin_transaction",
    "fin_risk_assessment",
    "fin_risk_rule",
    "fin_risk_alert",
    "biz_work_order",
    "biz_advisory_review",
    "biz_operation_advice_draft",
    "conversation_archive",
)


def purge(database_url: str | None = None) -> None:
    """清空 `_WIPE_TABLES`，保留 `_KEEP_TABLES`。幂等：跑两遍结果一致。"""
    engine = create_engine(database_url or get_settings().database_url)
    try:
        _check_table_coverage(engine)
        # TRUNCATE 是 DDL，在 MySQL 里会隐式提交。走 AUTOCOMMIT 免得 SQLAlchemy
        # 的事务状态与它打架。
        with engine.execution_options(isolation_level="AUTOCOMMIT").connect() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            try:
                for table in _WIPE_TABLES:
                    conn.execute(text(f"TRUNCATE TABLE `{table}`"))
            finally:
                conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    finally:
        engine.dispose()


def _check_table_coverage(engine: Engine) -> None:
    """库里有、清单里没有的表直接报错。

    加了新表却忘了加进清空清单，表现是「清完之后新表里还留着旧数据」——很难在答辩
    前发现。这里把它变成一个开跑就报的错，代价是加表时要顺手改一次本模块。
    """
    known = set(_WIPE_TABLES) | set(_KEEP_TABLES)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'"
            )
        )
        unknown = sorted(row[0] for row in rows if row[0] not in known)
    if unknown:
        raise RuntimeError(
            "清空清单没有覆盖这些表：" + "、".join(unknown) + "。请把它们加入 _WIPE_TABLES 或 _KEEP_TABLES。"
        )


def rebuild(database_url: str | None = None) -> None:
    """按基础种子重建：交给 `app.db.seed.seed()`，不在这里重写一份业务数据。"""
    seed(database_url)


def rebuild_graph(*, namespace: str | None = None, database_url: str | None = None) -> str:
    """全量重建知识图谱。Neo4j 连不上时返回一句告警而不是抛错。"""
    # 惰性 import：图谱那套依赖（neo4j / pymilvus）单次 import 上秒，
    # `--keep-graph` 与只清库这两条路径不必付这份开销。
    from app.knowledge_graph.service import rebuild as rebuild_projection
    from app.neo4j_client import get_neo4j

    settings = get_settings()
    url = database_url or settings.database_url
    # 复用应用自己的连接工厂：URI / 账号 / 建连超时都只有一处定义。
    driver = next(get_neo4j())
    engine = create_engine(url)
    try:
        with Session(engine) as db:
            status = rebuild_projection(
                db,
                driver,
                namespace=namespace or settings.neo4j_graph_namespace,
                now=datetime.now(),
            )
    except Exception as exc:  # noqa: BLE001 —— 图谱不可用不该拦住 MySQL 侧的演示
        return f"图谱重建未完成（{type(exc).__name__}: {exc}）。图谱增强类回答会走降级路径。"
    finally:
        engine.dispose()
        driver.close()
    return (
        f"图谱已全量重建：节点 {status['node_count']} 个、关系 {status['relationship_count']} 条，"
        f"耗时 {status['duration_ms']} ms。"
    )


def _report(database_url: str | None = None) -> None:
    engine = create_engine(database_url or get_settings().database_url)
    try:
        with engine.connect() as conn:
            for table in _REPORT_TABLES:
                count = conn.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar_one()
                print(f"  {table:<28} {count:>6}")
    finally:
        engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清空业务数据并按基础种子重建答辩演示数据")
    parser.add_argument("--database-url", default=None, help="默认取 settings.database_url（wealth 库）")
    parser.add_argument("--purge-only", action="store_true", help="只清空，不重建")
    parser.add_argument("--keep-graph", action="store_true", help="跳过知识图谱全量重建")
    parser.add_argument("--graph-namespace", default=None, help="图谱命名空间，默认取 settings")
    args = parser.parse_args(argv)

    print("[seed_demo] 清空业务数据（保留员工账号、知识库、迁移版本）...", flush=True)
    purge(args.database_url)

    if args.purge_only:
        print("[seed_demo] --purge-only：到此为止，未重建。")
        return 0

    print("[seed_demo] 按基础种子重建：5 位客户 / 7 只产品 / 20 条规则 / 历史成交回放 ...", flush=True)
    rebuild(args.database_url)

    if args.keep_graph:
        print("[seed_demo] --keep-graph：跳过图谱重建（Neo4j 里仍留着清理前的投影）。")
    else:
        print("[seed_demo] 全量重建知识图谱 ...", flush=True)
        print("[seed_demo] " + rebuild_graph(namespace=args.graph_namespace, database_url=args.database_url))

    print("[seed_demo] 当前库内：")
    _report(args.database_url)
    print("[seed_demo] 完成。口令统一 Test@1234；演示口径见 docs/demo-script.md，提问清单见 docs/demo-questions.md。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
