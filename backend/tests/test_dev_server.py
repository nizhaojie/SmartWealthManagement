"""开发启动入口（`scripts/dev_server.py`）的初始化开关判定。

守两件事：命令行开关压过环境变量——显式的选择不该被环境里的默认值反噬；以及只有
明确的真值才算「跳过」，空串、`false`、`0` 都该照常初始化。`--reset-seed` 是恢复
初始演示状态的那条路（`docs/demo-script.md`），不能被 `SKIP_DB_SETUP` 拦住——否则
「想复位却被环境变量静默跳过」正是最难查的那种。
"""

from __future__ import annotations

from scripts.dev_server import SKIP_SETUP_ENV, env_skips_setup, run_setup_requested


def test_runs_setup_by_default():
    assert run_setup_requested(reset_seed=False, skip_setup=False, env={}) is True


def test_env_var_skips_setup_only_for_truthy_values():
    assert env_skips_setup({SKIP_SETUP_ENV: "1"}) is True
    assert env_skips_setup({SKIP_SETUP_ENV: "TRUE"}) is True

    for value in ("", "0", "false", "no", "off", "  "):
        assert env_skips_setup({SKIP_SETUP_ENV: value}) is False, value


def test_skip_flag_skips_setup_without_the_env_var():
    assert run_setup_requested(reset_seed=False, skip_setup=True, env={}) is False


def test_env_var_skips_setup_but_reset_seed_wins():
    env = {SKIP_SETUP_ENV: "1"}

    assert run_setup_requested(reset_seed=False, skip_setup=False, env=env) is False
    assert run_setup_requested(reset_seed=True, skip_setup=False, env=env) is True
    # 两个开关同时给：复位是有意为之的那一个，压过跳过。
    assert run_setup_requested(reset_seed=True, skip_setup=True, env=env) is True
