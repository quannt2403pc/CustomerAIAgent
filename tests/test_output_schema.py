"""D1.19 — strict JSON output + writer.

Lược đồ ở đây là **hợp đồng với đề bài**. Test canh gác đúng những điều đề bài
nêu: 5 khoá bắt buộc, `trigger_time` = "20:00", `estimated_age_range` là
khoảng, `error_note` chỉ xuất hiện ở nhánh thiếu dữ liệu.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from pydantic import ValidationError

from app.schemas.output import (
    EstimatedDemographics,
    EthicalRapport,
    EveningCadence,
    ProfileData,
    StrictOutput,
    mask_facebook_url,
    mask_name,
    write_output_json,
)

URL = "https://www.facebook.com/example_user"

TEN_MESSAGES = [f"Tin nhắn số {i} đủ dài để trông như thật." for i in range(1, 11)]


def full_output(**overrides) -> StrictOutput:
    data = {
        "status": "SUCCESS",
        "facebook_url": URL,
        "profile_data": ProfileData(
            customer_name="Nguyễn Thị Lan",
            visual_context="Một người trưởng thành bế một em bé bên bánh sinh nhật.",
            estimated_demographics=EstimatedDemographics(
                gender="Nữ",
                estimated_age_range="28 - 38 tuổi",
                apparent_lifestyle="Mẹ chăm con nhỏ",
            ),
        ),
        "ethical_rapport": EthicalRapport(
            core_empathy_angle="Tôn vinh sự tần tảo của một người mẹ.",
            dialogue_sequence_10=TEN_MESSAGES,
            sales_mention_check="ZERO_SALES_CONFIRMED",
        ),
        "evening_cadence_20pm": EveningCadence(
            evening_hook_message="Tối rồi, mong bữa cơm nhà mình hôm nay thật ấm."
        ),
    }
    data.update(overrides)
    return StrictOutput(**data)


# ---------------------------------------------------------------------------
# Hợp đồng với đề bài
# ---------------------------------------------------------------------------
def test_success_output_has_exactly_the_five_required_keys() -> None:
    assert set(full_output().to_dict()) == {
        "status",
        "facebook_url",
        "profile_data",
        "ethical_rapport",
        "evening_cadence_20pm",
    }


def test_success_output_omits_error_note() -> None:
    """Đề bài không nêu `error_note` ở nhánh SUCCESS — in `null` là thêm nhiễu."""
    assert "error_note" not in full_output().to_dict()


def test_private_branch_includes_error_note() -> None:
    output = StrictOutput(
        status="PARTIAL_OR_PRIVATE",
        facebook_url=URL,
        error_note="Trang cá nhân bị khoá riêng tư, chỉ thu thập được metadata công khai.",
    )
    data = output.to_dict()
    assert data["status"] == "PARTIAL_OR_PRIVATE"
    assert "khoá riêng tư" in data["error_note"]


def test_nested_shape_matches_the_brief() -> None:
    data = full_output().to_dict()

    assert set(data["profile_data"]) == {
        "customer_name",
        "visual_context",
        "estimated_demographics",
    }
    assert set(data["profile_data"]["estimated_demographics"]) == {
        "gender",
        "estimated_age_range",
        "apparent_lifestyle",
    }
    assert set(data["ethical_rapport"]) == {
        "core_empathy_angle",
        "dialogue_sequence_10",
        "sales_mention_check",
    }
    assert set(data["evening_cadence_20pm"]) == {"trigger_time", "evening_hook_message"}


def test_trigger_time_is_pinned_to_2000() -> None:
    assert full_output().to_dict()["evening_cadence_20pm"]["trigger_time"] == "20:00"


def test_trigger_time_cannot_be_changed() -> None:
    """Để mốc giờ cấu hình được là mời output lệch đặc tả."""
    with pytest.raises(ValidationError):
        EveningCadence(trigger_time="21:00")


def test_unknown_field_is_refused() -> None:
    """`extra="forbid"`: khoá lạ nổ lúc dựng, không phải lúc người đánh giá mở file."""
    with pytest.raises(ValidationError):
        StrictOutput(status="SUCCESS", facebook_url=URL, khoa_la="x")


def test_unknown_status_is_refused() -> None:
    with pytest.raises(ValidationError):
        StrictOutput(status="DONE", facebook_url=URL)


def test_unknown_sales_check_is_refused() -> None:
    with pytest.raises(ValidationError):
        EthicalRapport(sales_mention_check="OK")


def test_sales_check_defaults_to_failed() -> None:
    """Mặc định phải là CHƯA xác nhận — luật L2."""
    assert EthicalRapport().sales_mention_check == "FAILED"


# ---------------------------------------------------------------------------
# Ràng buộc nội dung
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("count", [5, 7, 10])
def test_message_count_within_brief_range_is_accepted(count: int) -> None:
    assert len(EthicalRapport(dialogue_sequence_10=TEN_MESSAGES[:count]).dialogue_sequence_10) == (
        count
    )


@pytest.mark.parametrize("count", [1, 4, 11])
def test_message_count_outside_brief_range_is_refused(count: int) -> None:
    messages = (TEN_MESSAGES * 2)[:count]
    with pytest.raises(ValidationError, match="5–10"):
        EthicalRapport(dialogue_sequence_10=messages)


def test_empty_message_list_is_allowed_for_failed_branch() -> None:
    """Nhánh `FAILED_VALIDATION` không trả nội dung — mảng rỗng là đúng."""
    assert EthicalRapport(dialogue_sequence_10=[]).dialogue_sequence_10 == []


@pytest.mark.parametrize("value", ["25 - 35 tuổi", "28-38", "1 - 120 tuổi"])
def test_age_range_with_a_dash_is_accepted(value: str) -> None:
    assert EstimatedDemographics(estimated_age_range=value).estimated_age_range == value


@pytest.mark.parametrize("value", ["32 tuổi", "32", "khoảng trung niên"])
def test_bare_age_number_never_reaches_the_output(value: str) -> None:
    """Đề bài yêu cầu một **khoảng**. Lược đồ là chốt cuối chặn một con số."""
    with pytest.raises(ValidationError, match="khoảng"):
        EstimatedDemographics(estimated_age_range=value)


@pytest.mark.parametrize("value", ["Female", "Khác", "không rõ"])
def test_gender_outside_the_two_allowed_values_is_refused(value: str) -> None:
    with pytest.raises(ValidationError):
        EstimatedDemographics(gender=value)


def test_all_fact_fields_default_to_none() -> None:
    """Luật L1: không có bằng chứng thì `null`, không phải chuỗi rỗng."""
    data = StrictOutput(status="PARTIAL_OR_PRIVATE", facebook_url=URL).to_dict()
    assert data["profile_data"]["customer_name"] is None
    assert data["profile_data"]["visual_context"] is None
    assert all(v is None for v in data["profile_data"]["estimated_demographics"].values())
    assert data["evening_cadence_20pm"]["evening_hook_message"] is None


# ---------------------------------------------------------------------------
# Exit code
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "status, code",
    [
        ("SUCCESS", 0),
        # `PARTIAL_OR_PRIVATE` là kết quả ĐẠT (đề bài §4), không phải lỗi.
        ("PARTIAL_OR_PRIVATE", 0),
        ("FAILED_VALIDATION", 1),
        ("ERROR", 1),
    ],
)
def test_exit_code_mapping(status: str, code: int) -> None:
    assert StrictOutput(status=status, facebook_url=URL).exit_code == code


# ---------------------------------------------------------------------------
# JSON serialize
# ---------------------------------------------------------------------------
def test_json_keeps_vietnamese_characters() -> None:
    text = full_output().to_json()
    assert "Nguyễn Thị Lan" in text
    assert "\\u" not in text  # ensure_ascii=False


def test_json_round_trips_through_json_loads() -> None:
    """Đề bài: "parse trực tiếp bằng json.loads()"."""
    output = full_output()
    assert json.loads(output.to_json()) == output.to_dict()


def test_writer_produces_a_parseable_file(tmp_path) -> None:
    path = tmp_path / "output.json"
    write_output_json(full_output(), str(path))

    content = path.read_text(encoding="utf-8")
    assert json.loads(content)["status"] == "SUCCESS"
    assert content.endswith("\n")
    assert "Nguyễn Thị Lan" in content


def test_writer_creates_missing_directories(tmp_path) -> None:
    path = tmp_path / "sau" / "nua" / "output.json"
    write_output_json(full_output(), str(path))
    assert path.is_file()


def test_writer_leaves_no_temp_file_behind(tmp_path) -> None:
    path = tmp_path / "output.json"
    write_output_json(full_output(), str(path))
    assert [p.name for p in tmp_path.iterdir()] == ["output.json"]


def test_writer_does_not_corrupt_a_previous_file_on_rewrite(tmp_path) -> None:
    path = tmp_path / "output.json"
    write_output_json(full_output(), str(path))
    write_output_json(full_output(status="PARTIAL_OR_PRIVATE", error_note="x"), str(path))

    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "PARTIAL_OR_PRIVATE"


# ---------------------------------------------------------------------------
# --mask-pii
# ---------------------------------------------------------------------------
def test_masked_output_hides_name_and_url() -> None:
    masked = full_output().masked()

    assert masked.profile_data.customer_name == "N*** T*** L***"
    assert masked.facebook_url == "https://www.facebook.com/***"
    assert "example_user" not in masked.to_json()
    assert "Nguyễn Thị Lan" not in masked.to_json()


def test_masking_keeps_the_content_that_must_be_judged() -> None:
    """Che PII, **không** che nội dung tin nhắn — đó là thứ cần được đánh giá."""
    masked = full_output().masked()

    assert masked.ethical_rapport.dialogue_sequence_10 == TEN_MESSAGES
    assert masked.evening_cadence_20pm.evening_hook_message is not None
    assert masked.ethical_rapport.sales_mention_check == "ZERO_SALES_CONFIRMED"


def test_masking_does_not_mutate_the_original() -> None:
    output = full_output()
    output.masked()
    assert output.profile_data.customer_name == "Nguyễn Thị Lan"


def test_masking_a_profile_without_a_name_is_safe() -> None:
    output = StrictOutput(status="PARTIAL_OR_PRIVATE", facebook_url=URL)
    assert output.masked().profile_data.customer_name is None


@pytest.mark.parametrize(
    "name, expected",
    [("Nguyễn Thị Lan", "N*** T*** L***"), ("Lan", "L***"), ("   ", "***")],
)
def test_mask_name(name: str, expected: str) -> None:
    assert mask_name(name) == expected


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://www.facebook.com/abc", "https://www.facebook.com/***"),
        ("https://m.facebook.com/profile.php?id=1", "https://m.facebook.com/***"),
        ("(dán tay, không có URL)", "https://www.facebook.com/***"),
    ],
)
def test_mask_facebook_url(url: str, expected: str) -> None:
    assert mask_facebook_url(url) == expected


# ---------------------------------------------------------------------------
# Khớp nguyên văn ví dụ của đề bài
# ---------------------------------------------------------------------------
def test_brief_example_parses_into_the_schema() -> None:
    """Dán nguyên lược đồ ví dụ trong đề bài → phải dựng được, không khoá lạ."""
    example = {
        "status": "SUCCESS",
        "facebook_url": "https://www.facebook.com/example_user",
        "profile_data": {
            "customer_name": "Tên trích xuất được từ profile",
            "visual_context": "Ảnh mẹ bế con nhỏ mặc áo thun xanh bên bánh sinh nhật",
            "estimated_demographics": {
                "gender": "Nữ",
                "estimated_age_range": "25 - 35 tuổi",
                "apparent_lifestyle": "Mẹ bỉm chăm con",
            },
        },
        "ethical_rapport": {
            "core_empathy_angle": "Tôn vinh sự hy sinh của người mẹ lo toan cho con cái",
            "dialogue_sequence_10": TEN_MESSAGES[:5],
            "sales_mention_check": "ZERO_SALES_CONFIRMED",
        },
        "evening_cadence_20pm": {
            "trigger_time": "20:00",
            "evening_hook_message": "Câu chuyện mồi gửi lúc 20h tối.",
        },
    }
    assert StrictOutput(**example).to_dict() == example


def test_brief_private_example_parses_into_the_schema() -> None:
    example = {
        "status": "PARTIAL_OR_PRIVATE",
        "facebook_url": "https://www.facebook.com/example_user",
        "error_note": "Trang cá nhân bị khóa riêng tư, chỉ thu thập được metadata công khai...",
    }
    output = StrictOutput(**example)
    data = output.to_dict()

    assert data["status"] == example["status"]
    assert data["error_note"] == example["error_note"]
    # Ba khối còn lại vẫn có mặt với giá trị null (plan.md §5.7).
    assert data["profile_data"]["customer_name"] is None


def test_output_file_in_repo_is_gitignored() -> None:
    """`output.json` chứa PII của người thật — không được vào Git (luật L4)."""
    gitignore = (pathlib.Path(__file__).resolve().parents[1] / ".gitignore").read_text(
        encoding="utf-8"
    )
    assert "output.json" in gitignore
