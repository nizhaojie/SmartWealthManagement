"""开发启动入口：在**同一个解释器进程**里先做库初始化，再拉起 uvicorn。

**为什么合并。** 启动路径原本是两个进程：`python -m app.db.setup` 做初始化，
`python -m uvicorn` 跑服务。初始化本身只要一秒出头（迁移已是 no-op、seed 走幂等
分支、FAQ 有守卫），但每个新进程都要把 `app.main` 那套依赖图 import 一遍——实测
单次 import 4.2 秒（pymilvus 1.2s、neo4j 1.1s、pandas 0.8s、fastapi 0.7s）。两个
进程就是两遍这份开销。合成一个进程后，初始化与服务的 import 只付一次。

**跳过初始化。** `SKIP_DB_SETUP=1` 时不做初始化直接起服务。重复执行
`app.db.setup` 会把演示状态复位（余额对齐种子、历史成交删掉重放、预警与派生工单
一并删除），开发中反复重启后端窗口时并不总想要这件事；`--reset-seed` 反过来强制
初始化，用来恢复初始演示状态（`docs/demo-script.md` 里的那条口径）。

用法::

    cd backend
    python -m scripts.dev_server                  # 初始化 + uvicorn --reload
    SKIP_DB_SETUP=1 python -m scripts.dev_server  # 热启动：跳过初始化
    python -m scripts.dev_server --reset-seed     # 强制初始化（复位演示数据）
    python -m scripts.dev_server --no-reload      # 关掉热重载

`--reload` 下 uvicorn 会另起子进程托管应用。子进程按 uvicorn 的 reload 机制导入
`app.main`，本模块在它那里只是被 import 一遍（`__name__` 不是 `__main__`），因此
模块级只放 argparse/os/sys，库初始化留在函数里惰性 import——否则每次热重载都会
白付一次。
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence

SKIP_SETUP_ENV = "SKIP_DB_SETUP"

# 与 `DEMO_REPLAY` 一样是「设了就生效」的环境变量：只有明确的真值才算跳过。
_TRUTHY = {"1", "true", "yes", "on"}


def env_skips_setup(env: Mapping[str, str]) -> bool:
    return env.get(SKIP_SETUP_ENV, "").strip().lower() in _TRUTHY


def run_setup_requested(
    *,
    reset_seed: bool,
    skip_setup: bool,
    env: Mapping[str, str] | None = None,
) -> bool:
    """是否执行库初始化：`--reset-seed` 压过一切，`--skip-setup` 压过环境变量。

    两个开关是显式的命令行选择，环境变量只是默认值——所以命令行的「跳过」不该被
    环境里的空串或 `0` 反噬，命令行的「复位」也不该被环境变量拦住。
    """
    if reset_seed:
        return True
    if skip_setup:
        return False
    return not env_skips_setup(os.environ if env is None else env)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="开发启动：初始化数据库后以 uvicorn 拉起后端")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    parser.add_argument("--no-reload", action="store_true", help="关掉热重载")
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help=f"跳过库初始化（等价于 {SKIP_SETUP_ENV}=1）",
    )
    parser.add_argument(
        "--reset-seed",
        action="store_true",
        help="强制库初始化：迁移 + 种子 + FAQ，把演示状态复位",
    )
    args = parser.parse_args(argv)

    if run_setup_requested(reset_seed=args.reset_seed, skip_setup=args.skip_setup):
        # 惰性 import：跳过初始化的那条路径不必付这份 import 费用。
        from app.db.setup import setup

        print("[dev_server] 初始化数据库：迁移 + 种子 + FAQ + 受限账号 ...", flush=True)
        setup()
    else:
        print(
            f"[dev_server] 跳过库初始化（{SKIP_SETUP_ENV}=1 / --skip-setup）；"
            "要恢复初始演示状态请加 --reset-seed",
            flush=True,
        )

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=not args.no_reload,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
