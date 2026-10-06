"""Strict JSON output — **nguồn sự thật duy nhất** về hình dạng đầu ra.

Đề bài yêu cầu đúng một chuỗi JSON parse được bằng `json.loads()`. Lược đồ ở
đây là hợp đồng đó, viết bằng Pydantic v2 với `extra="forbid"`: thêm một khoá
lạ là lỗi ngay lúc dựng, không phải lúc người đánh giá mở file.

Hai quyết định có chủ đích:

- `dialogue_sequence_10` giữ **đúng tên của đề bài** dù số tin có thể 5–10.
  Đổi tên cho "hợp lý hơn" là lệch đặc tả.
- `error_note` chỉ xuất hiện khi có giá trị. Đề bài nêu nó ở nhánh
  `PARTIAL_OR_PRIVATE`; in `"error_note": null` ở nhánh `SUCCESS` là thêm nhiễu
  vào một hợp đồng đã rõ.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["SUCCESS", "PARTIAL_OR_PRIVATE", "FAILED_VALIDATION", "ERROR"]
SalesCheck = Literal["ZERO_SALES_CONFIRMED", "FAILED"]

TRIGGER_TIME = "20:00"

MIN_MESSAGES = 5
MAX_MESSAGES = 10


class _Strict(BaseModel):
    """Mọi model ở đây cấm field lạ."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EstimatedDemographics(_Strict):
    """Ước lượng nhân khẩu học. `None` nghĩa là **không có bằng chứng** (luật L1)."""

    gender: Literal["Nữ", "Nam"] | None = None
    estimated_age_range: str | None = None
    apparent_lifestyle: str | None = None

    @field_validator("estimated_age_range")
    @classmethod
    def _must_be_a_range(cls, value: str | None) -> str | None:
        """Chặn một con số lọt ra output — đề bài yêu cầu một **khoảng**."""
        if value is None:
            return None
        if "-" not in value:
            raise ValueError(
                f"estimated_age_range phải là một khoảng (vd '25 - 35 tuổi'), nhận {value!r}"
            )
        return value


class ProfileData(_Strict):
    customer_name: str | None = None
    visual_context: str | None = None
    estimated_demographics: EstimatedDemographics = Field(default_factory=EstimatedDemographics)


class EthicalRapport(_Strict):
    core_empathy_angle: str | None = None
    # Tên field theo **đúng** đề bài, kể cả khi chuỗi có 5–10 tin.
    dialogue_sequence_10: list[str] = Field(default_factory=list)
    sales_mention_check: SalesCheck = "FAILED"

    @field_validator("dialogue_sequence_10")
    @classmethod
    def _count_within_brief_range(cls, value: list[str]) -> list[str]:
        """Rỗng thì được (nhánh thất bại), nhưng có thì phải 5–10 tin."""
        if value and not MIN_MESSAGES <= len(value) <= MAX_MESSAGES:
            raise ValueError(
                f"dialogue_sequence_10 phải có {MIN_MESSAGES}–{MAX_MESSAGES} tin, "
                f"nhận {len(value)}"
            )
        return value


class EveningCadence(_Strict):
    # Hằng số theo đề bài. Để cấu hình được là mời output lệch đặc tả.
    trigger_time: Literal["20:00"] = TRIGGER_TIME
    evening_hook_message: str | None = None


class StrictOutput(_Strict):
    """Toàn bộ đầu ra của một lần chạy."""

    status: Status
    facebook_url: str
    profile_data: ProfileData = Field(default_factory=ProfileData)
    ethical_rapport: EthicalRapport = Field(default_factory=EthicalRapport)
    evening_cadence_20pm: EveningCadence = Field(default_factory=EveningCadence)
    error_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Dict để serialize. Bỏ `error_note` khi không có."""
        data = self.model_dump(mode="json")
        if data.get("error_note") is None:
            data.pop("error_note", None)
        return data

    def to_json(self, *, indent: int | None = 2) -> str:
        """JSON UTF-8 giữ nguyên tiếng Việt (`ensure_ascii=False`)."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @property
    def exit_code(self) -> int:
        """0 cho `SUCCESS`/`PARTIAL_OR_PRIVATE`, 1 cho `ERROR`/`FAILED_VALIDATION`.

        `PARTIAL_OR_PRIVATE` là **kết quả đạt** (đề bài §4): đọc không được thì
        báo thật. Trả mã lỗi cho nó sẽ làm script gọi CLI tưởng hệ thống hỏng.
        """
        return 0 if self.status in ("SUCCESS", "PARTIAL_OR_PRIVATE") else 1

    def masked(self) -> StrictOutput:
        """Bản che PII để chia sẻ rộng (`--mask-pii`).

        Che tên và URL — hai thứ định danh trực tiếp một người thật. Nội dung
        tin nhắn giữ nguyên vì đó là thứ cần được đánh giá.
        """
        clone = self.model_copy(deep=True)
        clone.facebook_url = mask_facebook_url(self.facebook_url)
        if clone.profile_data.customer_name:
            clone.profile_data.customer_name = mask_name(clone.profile_data.customer_name)
        return clone


def write_output_json(output: StrictOutput, path: str) -> None:
    """Ghi `output.json` — UTF-8, `ensure_ascii=False`, có newline cuối file.

    Ghi qua file tạm rồi `replace`: một lần chạy bị ngắt giữa lúc ghi không được
    để lại `output.json` hỏng mà vẫn trông như có kết quả.
    """
    import os
    import pathlib

    target = pathlib.Path(path)
    if target.parent != pathlib.Path():
        target.parent.mkdir(parents=True, exist_ok=True)

    temp = target.with_name(target.name + ".tmp")
    temp.write_text(output.to_json() + "\n", encoding="utf-8")
    os.replace(temp, target)


def mask_name(name: str) -> str:
    """`Nguyễn Thị Lan` → `N*** T*** L***`."""
    parts = [part for part in name.split() if part]
    return " ".join(f"{part[0]}***" for part in parts) if parts else "***"


def mask_facebook_url(url: str) -> str:
    """Giữ nguyên dạng URL để vẫn thấy đó là link Facebook, che phần định danh."""
    marker = "facebook.com/"
    index = url.find(marker)
    if index == -1:
        return "https://www.facebook.com/***"
    return url[: index + len(marker)] + "***"
