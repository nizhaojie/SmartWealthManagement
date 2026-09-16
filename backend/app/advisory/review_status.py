"""审核状态与操作的字面量——被 app.advisory.graph（写状态的一侧）与
app.advisory.review（加锁、发起恢复的一侧）共用，避免两处各写一份字符串。
"""

STATUS_PENDING = "待审"
STATUS_IN_PROGRESS = "处理中"
STATUS_RELEASED = "已放行"
STATUS_REJECTED = "已驳回"

ACTION_RELEASE = "放行"
ACTION_REJECT = "驳回"
