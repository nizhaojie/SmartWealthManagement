"""高风险意图识别：纯函数，直接测输入输出。

它决定了「要不要提醒风控看一眼」，因此断言集中在两件事上：哪些问话算苗头，以及
理由里写的是「打听」还是「反复打听」——后者是数出来的，不是猜的。
"""

from app.agent.risk_intent import detect_risk_intent


def test_an_ordinary_question_is_not_a_risk_signal():
    assert detect_risk_intent("这款产品的管理费率是多少") is None


def test_probing_transfer_limits_is_flagged():
    signal = detect_risk_intent("我想问一下，我的转账限额是多少")

    assert signal is not None
    assert signal.code == "TRANSFER_LIMIT"
    assert "转账限额" in signal.reason


def test_a_question_asked_once_is_not_described_as_repeated():
    signal = detect_risk_intent("转账限额是多少")
    assert signal is not None
    assert not signal.reason.startswith("反复")


def test_asking_the_same_thing_again_in_the_session_reads_as_repeated():
    history = [
        {"role": "user", "content": "我的转账限额是多少"},
        {"role": "assistant", "content": "建议您拨打客服热线核实。"},
    ]

    signal = detect_risk_intent("那如果我分几笔转出去呢", history=history)

    assert signal is not None
    assert signal.code == "TRANSFER_LIMIT"
    assert signal.reason.startswith("反复")


def test_a_different_signal_in_the_history_does_not_count_as_repetition():
    history = [{"role": "user", "content": "境外汇款手续费怎么算"}]

    signal = detect_risk_intent("转账限额是多少", history=history)

    assert signal is not None
    assert signal.code == "TRANSFER_LIMIT"
    assert not signal.reason.startswith("反复")


def test_suspicious_money_flow_is_a_risk_signal():
    signal = detect_risk_intent("朋友让我帮忙过一下账，会有问题吗")

    assert signal is not None
    assert signal.code == "SUSPICIOUS_FLOW"
