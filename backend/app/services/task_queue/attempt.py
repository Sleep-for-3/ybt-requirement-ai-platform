"""R02/C05: 单次尝试的**执行权协议**（attempt execution authority）。

背景（复核 R02）：租约可能在 handler **运行期间**丢失，而领域 handler 通过 ``_complete``
提交自己的对象（StoredFile / 通知 / 审计）。队列层只在 handler 返回**之后**检查 ``lease_lost``，
那时旧尝试已经把成功结果与通知写出去了 —— 检查太晚。

因此本模块把「不可变的 attempt token」与「是否已失租」带到**领域提交边界**，
让校验与持久化处于同一执行权协议之下：

* ``bind_attempt`` / ``current_attempt``：把执行权绑定到本次运行使用的 ``Session``
  （用 ``Session.info`` 而不是线程局部变量，因为领域代码可能把同一个 Session 交给
  线程池或 ``asyncio.run`` 执行，线程局部变量在那里会丢失）；
* ``AttemptAuthority.still_owns``：只读预检，用于廉价地提前退出；
* ``AttemptAuthority.fence_commit``：在**同一事务**内对 job 行做带 owner 条件的加锁读取，
  只有本尝试仍持有该 job 时才 ``commit`` 调用方挂起的领域写入；否则整体 ``rollback`` ——
  于是失租的旧尝试不会提交任何 StoredFile / 通知 / 审计行。

``AttemptLeaseLost`` 让 handler 能显式表达「我已失租」，队列层据此回滚并如实上报接管者的状态，
而不是把它当成普通的业务失败。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.models import BackgroundJob

# 绑定在 Session.info 上的键。用 Session 承载执行权，使领域代码在多线程/asyncio 边界之后
# 仍然能拿到同一个 attempt 的身份，而不依赖线程局部状态。
ATTEMPT_INFO_KEY = "ybt_attempt_authority"


class AttemptLeaseLost(RuntimeError):
    """本尝试已不再持有该 job；调用方必须回滚并采纳接管者的结果。"""


@dataclass(frozen=True)
class AttemptAuthority:
    """一次尝试的执行权：不可变的 owner token + 失租信号。"""

    job_id: int
    owner: str
    lost: threading.Event = field(default_factory=threading.Event)

    def _committed_owner(self, db: Session) -> str | None:
        """在**新事务**中读取已提交的 owner。

        不能只用调用方那个 Session 查询：领域 handler 往往已经开启了一个读事务
        （例如先 ``db.get(Project, ...)``），而该事务的快照早于接管者的提交。
        在新 Session/新事务里读，PostgreSQL（READ COMMITTED）与 SQLite 都能看到已提交的接管。
        """

        try:
            factory = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
        except Exception:  # noqa: BLE001 - 无法开新会话时退回当前会话
            return db.scalar(
                select(BackgroundJob.lease_owner).where(BackgroundJob.id == self.job_id)
            )
        with factory() as probe:
            return probe.scalar(
                select(BackgroundJob.lease_owner).where(BackgroundJob.id == self.job_id)
            )

    def still_owns(self, db: Session) -> bool:
        """只读预检：本尝试是否仍持有该 job（读取已提交状态）。"""

        if self.lost.is_set():
            return False
        return self._committed_owner(db) == self.owner

    def fence_commit(self, db: Session) -> bool:
        """只有当本尝试仍持有 job 时，才提交挂起的领域写入。

        顺序（同一执行权协议）：
        1. ``flush`` 把挂起的领域 INSERT 发到事务里（尚未提交）；
        2. 在新事务中确认 owner 仍是自己 —— 这是权威判定，不受调用方旧快照影响；
        3. 在**本事务**内用带 owner 条件的受限 UPDATE 再次确认并锁定该行；
        4. 只有两道校验都通过才 ``commit``，否则整体 ``rollback`` ——
           调用方挂起的审计/通知/StoredFile 插入一并作废。
        """

        if self.lost.is_set():
            db.rollback()
            return False
        db.flush()
        if self._committed_owner(db) != self.owner:
            db.rollback()
            return False
        guarded = db.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == self.job_id, BackgroundJob.lease_owner == self.owner)
            .values(lease_expires_at=BackgroundJob.lease_expires_at)
            .execution_options(synchronize_session=False)
        ).rowcount
        if guarded != 1:
            db.rollback()
            return False
        db.commit()
        return True


def bind_attempt(db: Session, authority: AttemptAuthority) -> None:
    db.info[ATTEMPT_INFO_KEY] = authority


def release_attempt(db: Session) -> None:
    db.info.pop(ATTEMPT_INFO_KEY, None)


def current_attempt(db: Session) -> AttemptAuthority | None:
    if db is None:
        return None
    return db.info.get(ATTEMPT_INFO_KEY)
