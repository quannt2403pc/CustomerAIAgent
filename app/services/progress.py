"""Tiến trình từng bước của một lần phân tích (task.md D2.3, D2.8).

Vì sao cần một kiểu riêng thay vì log: một lần phân tích mất **hàng chục giây**
(đo thật D1.21: 70s). Spinner quay suốt 70 giây không nói được "đang ở đâu" và
cũng không phân biệt được "đang chạy" với "đã treo". UI cần mốc thật, mà mốc thật
chỉ có pipeline biết.

Các bước là **hằng số**, không phải chuỗi tuỳ ý: UI vẽ timeline theo đúng danh
sách này, nên một chuỗi viết sai chính tả sẽ tạo ra một bước lạ thay vì báo lỗi.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol


class Step(StrEnum):
    """Sáu bước người vận hành nhìn thấy.

    Kế hoạch (plan.md §6.3) ban đầu nêu 5 bước và gộp hook 20h vào "Kiểm duyệt".
    Tách ra vì hook 20h là **một deliverable riêng của đề bài**
    (`evening_cadence_20pm`) và nó có vòng sinh lại riêng — gộp vào bước khác thì
    khi hook bị loại, UI hiện "lỗi kiểm duyệt" mà không nói lỗi ở chuỗi tin nhắn
    hay ở hook (task.md I-38).
    """

    COLLECT = "collect"
    IMAGES = "images"
    PROFILE = "profile"
    MESSAGES = "messages"
    HOOK = "hook"
    MODERATION = "moderation"


STEP_LABELS: dict[Step, str] = {
    Step.COLLECT: "Thu thập",
    Step.IMAGES: "Ảnh",
    Step.PROFILE: "Profile",
    Step.MESSAGES: "Tin nhắn",
    Step.HOOK: "Hook 20h",
    Step.MODERATION: "Kiểm duyệt",
}


class State(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    # `SKIPPED` khác `FAILED`: trang private thì bước Ảnh **không có gì để làm**,
    # đó không phải lỗi. Gộp hai thứ này làm UI báo đỏ một kết quả đúng.
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class StepState:
    step: Step
    state: State = State.PENDING
    note: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "step": str(self.step),
            "label": STEP_LABELS[self.step],
            "state": str(self.state),
            "note": self.note,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class ProgressSink(Protocol):
    """Cái mà pipeline gọi. Giữ hẹp để pipeline không phụ thuộc vào tầng API."""

    def mark(self, step: Step, state: State, note: str = "") -> None: ...


@dataclass
class ProgressTracker:
    """Giữ trạng thái 6 bước. Không async, không I/O — chỉ là bộ nhớ."""

    steps: dict[Step, StepState] = field(
        default_factory=lambda: {step: StepState(step=step) for step in Step}
    )

    def mark(self, step: Step, state: State, note: str = "") -> None:
        entry = self.steps[step]
        now = datetime.now(UTC)
        if state is State.RUNNING and entry.started_at is None:
            entry.started_at = now
        if state in (State.DONE, State.SKIPPED, State.FAILED):
            entry.finished_at = now
        entry.state = state
        if note:
            entry.note = note

    def to_list(self) -> list[dict[str, object]]:
        """Theo đúng thứ tự khai báo của `Step` — UI vẽ timeline tuần tự."""
        return [self.steps[step].to_dict() for step in Step]


class NullProgress:
    """Dùng khi không ai quan tâm tiến trình (CLI, test).

    Có một đối tượng rỗng thay vì `if progress is not None` rải khắp pipeline:
    mỗi chỗ kiểm `None` là một chỗ có thể quên kiểm.
    """

    def mark(self, step: Step, state: State, note: str = "") -> None:
        return None
