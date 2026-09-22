"""后端依赖自检脚本（`scripts/check_deps.py`）的判定口径。

它守的是「pyproject 改了、环境没跟上」这道缺口：`jieba` / `rank_bm25` 加进
dependencies 后没进 conda 环境，直到启动后端才以 `ModuleNotFoundError` 暴露。
判定必须落在**已安装分发包的元数据**上而不是 import 名，否则 `argon2-cffi`、
`python-docx` 这类包名一变就误报。
"""

from __future__ import annotations

from scripts.check_deps import (
    declared_requirements,
    distribution_name,
    missing_requirements,
)


def test_distribution_name_strips_extras_and_version_specifiers():
    assert distribution_name("uvicorn[standard]>=0.32.0") == "uvicorn"
    assert distribution_name("uvicorn[standard]==0.32.0") == "uvicorn"
    assert distribution_name("rank_bm25>=0.2.2") == "rank_bm25"
    assert distribution_name("pyjwt>=2.9.0") == "pyjwt"
    assert distribution_name("  fastapi  ") == "fastapi"


def test_declared_requirements_reads_pyproject_in_order():
    requirements = declared_requirements()

    assert requirements, "pyproject.toml 的 dependencies 不该为空"
    assert requirements[0].startswith("fastapi")
    assert any(requirement.startswith("rank_bm25") for requirement in requirements)


def test_declared_requirements_appends_the_dev_extra_on_demand():
    runtime = declared_requirements()
    with_dev = declared_requirements(with_dev=True)

    # 运行期一组原样在前，dev 一组续在后面：`--dev` 是加法，不是替换。
    assert with_dev[: len(runtime)] == runtime
    assert any(requirement.startswith("pytest") for requirement in with_dev[len(runtime) :])
    assert not any(requirement.startswith("pytest") for requirement in runtime)


def test_missing_requirements_flags_only_the_absent_distribution():
    # 两个真装了的包 + 一个不可能存在的包：只报后者，且原样带回版本约束。
    missing = missing_requirements(
        ["fastapi>=0.115.0", "rank_bm25>=0.2.2", "definitely-not-a-package>=1.0"]
    )

    assert missing == ["definitely-not-a-package>=1.0"]


def test_missing_requirements_treats_underscore_and_dash_names_as_equal():
    # PEP 503：规范名里 `_` 与 `-` 等价，元数据查找不该因写法不同而误报。
    assert missing_requirements(["rank-bm25", "rank_bm25"]) == []


def test_running_environment_satisfies_every_declared_requirement():
    """跑测试的解释器必须满足 pyproject 的全部声明——本次 bug 的回归钉子。"""
    assert missing_requirements(declared_requirements()) == []
