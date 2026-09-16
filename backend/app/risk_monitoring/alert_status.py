"""预警自身处置状态的唯一字面量来源。

产生预警的一侧（`app.risk_monitoring.alerting`）写下「未处理」，做出判定的一侧
（`app.risk_monitoring.disposition`）把它推到「已排除」或「已升级」。两处共用同一
份字符串，不各写一份。

**系统不自动关闭任何预警**：这里不存在第四个状态，也没有任何代码路径能在没有人
参与的情况下离开「未处理」。置信度再低、放得再久、订阅方报错，预警都留在原地等
人处置——「低置信自动关掉能减少工作量」是一个很容易被当作优化提出的想法，而它会
让预警被系统悄悄消化掉。
"""

ALERT_STATUS_OPEN = "未处理"
ALERT_STATUS_EXCLUDED = "已排除"
ALERT_STATUS_ESCALATED = "已升级"
