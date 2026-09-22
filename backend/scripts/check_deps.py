"""核对 `pyproject.toml` 声明的运行期依赖是否都已装进当前解释器。

**为什么需要它。** `pyproject.toml` 的 `project.dependencies` 是后端运行期依赖的
唯一来源，但解释器是**环境级**的：`backend/.venv` 与 conda 环境 `wealth-backend`
都是先建好、后装依赖。新增一条依赖时老环境不会自动跟上，缺口要等到真正用到它的
那一刻才炸——ADR-0022 引入的 `jieba` / `rank_bm25` 就属于这一类：环境里没装，
报告出来的却是启动后端时的 `ModuleNotFoundError: No module named 'rank_bm25'`，
离「该装依赖」这个动作已经很远。

本脚本把这件事挪到启动之前：逐条核对声明里的分发包，缺失的直接打印，加 `--install`
时顺手交给 pip 装掉。判定口径与 pip 一致——看**已安装分发包的元数据**（`importlib
.metadata`），不是 `import`——因此不需要维护「分发包名 → import 名」的映射表
（`argon2-cffi` → `argon2`、`python-docx` → `docx` 那类映射本身就是最容易过期的东西）。

用法::

    cd backend
    python -m scripts.check_deps                  # 只检查，缺依赖时退出码 1
    python -m scripts.check_deps --install        # 缺什么装什么（首次需要联网）
    python -m scripts.check_deps --dev --install  # 并上 dev 一组（pytest/httpx/mypy）

`--dev` 刻意不并进启动路径：后端跑起来只需要 `project.dependencies`，把 mypy 拉进
启动前检查只会让「没装测试依赖」变成「后端起不来」。它服务于另一件事——环境与
`pyproject.toml` 的漂移是同一类问题，dev 一组同样是显式安装的，同样值得一条命令问清楚。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = BACKEND_DIR / "pyproject.toml"

# PEP 508 声明里分发包名之后允许出现的分隔符：`uvicorn[standard]>=0.32.0` → `uvicorn`。
_NAME_SEPARATOR = re.compile(r"[\s\[<>=!~;]")


def declared_requirements(
    pyproject_path: Path = PYPROJECT_PATH, *, with_dev: bool = False
) -> list[str]:
    """`project.dependencies` 的原始声明；`with_dev=True` 时再并上 dev 一组。"""
    project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]
    requirements = list(project["dependencies"])
    if with_dev:
        extras = project.get("optional-dependencies", {})
        requirements += list(extras.get("dev", []))
    return requirements


def distribution_name(requirement: str) -> str:
    """从一条声明里取出分发包名（去掉 extra 与版本约束）。"""
    return _NAME_SEPARATOR.split(requirement.strip(), 1)[0]


def missing_requirements(requirements: Sequence[str]) -> list[str]:
    """当前解释器里没有的依赖，返回原始声明（带版本约束）以便原样交给 pip。"""
    missing: list[str] = []
    for requirement in requirements:
        try:
            version(distribution_name(requirement))
        except PackageNotFoundError:
            missing.append(requirement)
    return missing


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="核对后端运行期依赖是否齐备")
    parser.add_argument(
        "--install",
        action="store_true",
        help="缺失的依赖直接交给 pip 安装（需要联网）",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="连同 dev 一组（pytest/httpx/mypy）一起核对——跑测试才需要，不在启动路径上",
    )
    args = parser.parse_args(argv)

    requirements = declared_requirements(with_dev=args.dev)
    missing = missing_requirements(requirements)
    if not missing:
        print(f"后端依赖齐备（{len(requirements)} 条）")
        return 0

    print("后端依赖缺失：")
    for requirement in missing:
        print(f"  - {requirement}")

    if not args.install:
        hint = "python -m scripts.check_deps --install"
        if not args.dev:
            hint += "（跑测试再加 --dev）"
        print(f"\n请执行 `{hint}` 或 `pip install -e .[dev]` 补装。")
        return 1

    print("\n正在安装缺失依赖（首次需要联网）...")
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "install", *missing],
        cwd=BACKEND_DIR,
        check=False,
    )
    if completed.returncode != 0:
        print("安装失败，请检查网络或手动执行 `pip install -e .`。")
        return completed.returncode

    still_missing = missing_requirements(requirements)
    if still_missing:
        print("安装后仍然缺失：")
        for requirement in still_missing:
            print(f"  - {requirement}")
        return 1

    print("依赖已补齐。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
