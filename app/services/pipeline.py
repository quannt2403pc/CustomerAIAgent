"""Vòng sinh — kiểm duyệt — sinh lại, và hàm chạy trọn một lần phân tích.

Luật vòng sinh lại: tối đa **2 lượt sinh lại** (tổng 3 lần gọi). Hết lượt mà
vẫn fail → `FAILED_VALIDATION` và **không trả nội dung bẩn ra output**. Trả nội
dung bẩn kèm một cờ "chưa xác nhận" là mời người vận hành copy nó đi gửi.

Mỗi lượt sinh lại được nói **đúng** điều đã sai ở lượt trước. Sinh lại với
prompt y nguyên chỉ là hy vọng vào xác suất.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from app.collectors import mbasic, og_meta, playwright_dom
from app.collectors.avatar import fetch_and_normalize, fetch_public_photos
from app.collectors.evidence import EvidenceBundle
from app.collectors.manual import collect_from_text
from app.collectors.throttle import HostRateLimiter
from app.collectors.url import normalize_facebook_url
from app.core.config import get_settings
from app.core.logging import get_logger
from app.llm.base import LLMGateway
from app.schemas.output import (
    EstimatedDemographics,
    EthicalRapport,
    EveningCadence,
    ProfileData,
    StrictOutput,
)
from app.services.evening_hook import EveningHookResult, generate_evening_hook
from app.services.profiler import ProfileResult, build_profile
from app.services.rapport import RapportResult, generate_sequence, style_feedback
from app.services.validators import (
    GroundingReport,
    ZeroSalesReport,
    validate_grounding,
    validate_zero_sales,
)

log = get_logger(__name__)

STATUS_FAILED_VALIDATION = "FAILED_VALIDATION"
MAX_REGENERATE_ATTEMPTS = 2

# Dùng khi chạy `--profile-file` mà không kèm `--url`: nói thật là không có URL,
# thay vì bịa ra một link trông như thật.
MANUAL_ONLY_URL = "(dán tay, không có URL)"


@dataclass
class ValidatedSequence:
    """Chuỗi tin nhắn đã qua kiểm duyệt — hoặc đã hết lượt mà vẫn chưa sạch."""

    passed: bool
    attempts: int
    messages: list[str] = field(default_factory=list)
    empathy_angle: str | None = None
    sales_report: ZeroSalesReport | None = None
    grounding_report: GroundingReport | None = None
    rapport: RapportResult | None = None
    rejected_reasons: list[str] = field(default_factory=list)

    @property
    def sales_check(self) -> str:
        """`ZERO_SALES_CONFIRMED` chỉ khi **toàn bộ** vòng kiểm duyệt đã qua.

        `self.passed` là điều kiện cần, không chỉ `sales_report.passed`. Đã gặp
        thật (task.md I-21): chuỗi bị loại vì **grounding**, nhưng lượt cuối lại
        sạch về mặt bán hàng, nên cờ ra `ZERO_SALES_CONFIRMED` trong khi
        `dialogue_sequence_10` là `[]` — xác nhận "0% chào bán" cho nội dung
        không tồn tại, vừa vô nghĩa vừa làm người đọc tưởng nội dung đã được duyệt.
        """
        if not self.passed or not self.messages:
            return "FAILED"
        return self.sales_report.sales_check if self.sales_report is not None else "FAILED"

    def report_for_db(self) -> dict[str, object]:
        return {
            "attempts": self.attempts,
            "passed": self.passed,
            "grounding": self.grounding_report.to_dict() if self.grounding_report else None,
            "zero_sales": self.sales_report.to_dict() if self.sales_report else None,
            "rejected_reasons": self.rejected_reasons,
        }


async def generate_validated_sequence(
    profile: ProfileResult,
    evidence_corpus: str,
    gateway: LLMGateway,
    *,
    model: str,
    n_messages: int | None = None,
    temperature: float = 0.9,
    max_attempts: int = MAX_REGENERATE_ATTEMPTS,
) -> ValidatedSequence:
    """Sinh → kiểm → sinh lại, tối đa `max_attempts` lượt sinh lại."""
    total_attempts = max_attempts + 1
    rejected: list[str] = []
    feedback = ""
    empathy_angle: str | None = None
    empathy_grounded: str | None = None
    last: RapportResult | None = None
    last_sales: ZeroSalesReport | None = None
    last_grounding: GroundingReport | None = None

    for attempt in range(1, total_attempts + 1):
        rapport = await generate_sequence(
            profile,
            evidence_corpus,
            gateway,
            model=model,
            n_messages=n_messages,
            temperature=temperature,
            empathy_angle=empathy_angle,
            empathy_grounded_in=empathy_grounded,
            extra_instruction=feedback,
        )
        last = rapport
        # Giữ lại góc thấu cảm của lượt đầu: nó đã có `grounded_in` thật, và
        # sinh lại chỉ cần sửa *cách viết*, không cần đổi *góc nhìn*.
        empathy_angle = empathy_angle or rapport.empathy_angle
        empathy_grounded = empathy_grounded or rapport.empathy_grounded_in

        grounding = validate_grounding(rapport.messages, evidence_corpus)
        sales = await validate_zero_sales(rapport.messages, gateway, model=model)
        last_grounding, last_sales = grounding, sales

        problems = [
            part
            for part in (
                grounding.feedback(),
                sales.feedback(),
                style_feedback(rapport.style_issues),
            )
            if part
        ]

        if not problems:
            log.info("Chuỗi tin nhắn qua kiểm duyệt ở lượt %d", attempt)
            return ValidatedSequence(
                passed=True,
                attempts=attempt,
                messages=rapport.messages,
                empathy_angle=empathy_angle,
                sales_report=sales,
                grounding_report=grounding,
                rapport=rapport,
                rejected_reasons=rejected,
            )

        rejected.append(f"lượt {attempt}: " + " | ".join(problems))
        feedback = "\n\n".join(problems)
        log.warning("Lượt %d/%d không qua kiểm duyệt, sinh lại", attempt, total_attempts)

    # Hết lượt. KHÔNG trả `messages` — nội dung bẩn không được rời khỏi đây.
    log.error("Hết %d lượt mà chuỗi tin nhắn vẫn không qua kiểm duyệt", total_attempts)
    return ValidatedSequence(
        passed=False,
        attempts=total_attempts,
        messages=[],
        empathy_angle=empathy_angle,
        sales_report=last_sales,
        grounding_report=last_grounding,
        rapport=last,
        rejected_reasons=rejected,
    )


# ===========================================================================
# Chạy trọn một lần phân tích (D1.19)
# ===========================================================================
@dataclass
class AnalysisOutcome:
    """Kết quả một lần chạy, kèm mọi thứ cần lưu DB."""

    output: StrictOutput
    bundle: EvidenceBundle
    profile: ProfileResult | None = None
    sequence: ValidatedSequence | None = None
    hook: EveningHookResult | None = None
    layers_used: list[str] = field(default_factory=list)


async def run_analysis(
    *,
    gateway: LLMGateway,
    model: str,
    url: str | None = None,
    profile_text: str | None = None,
    n_messages: int | None = None,
    temperature: float = 0.9,
    playwright_enabled: bool = False,
    facebook_cookie: str | None = None,
    recent_hooks: list[str] | None = None,
    client: httpx.AsyncClient | None = None,
    upload_dir: str | None = None,
) -> AnalysisOutcome:
    """Thu thập → profile → tin nhắn → hook → strict JSON.

    Không raise vì lý do *nội dung*: trang private, model lỗi, kiểm duyệt fail —
    tất cả thành một `status` + `error_note` trung thực. Chỉ URL sai định dạng
    mới raise (`InvalidFacebookUrl`), vì đó là lỗi của người gọi.
    """
    settings = get_settings()
    limiter = HostRateLimiter(settings.collector_min_interval_seconds)
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(settings.collector_timeout_seconds), follow_redirects=True
    )

    try:
        target = normalize_facebook_url(url) if url else None
        facebook_url = target.canonical_url if target else MANUAL_ONLY_URL
        bundle = EvidenceBundle(
            url_key=target.url_key if target else "manual:local",
            facebook_url=facebook_url,
        )

        # --- Thu thập -----------------------------------------------------
        if target is not None:
            await limiter.wait(target.canonical_url)
            await og_meta.collect(target, bundle, client=client)
            await mbasic.collect(
                target, bundle, client=client, limiter=limiter, cookie=facebook_cookie
            )
            # L3 chỉ chạy khi người dùng bật. Nó nặng (~500MB Chromium) nhưng là
            # đường thực tế duy nhất lấy được bio/bài viết, vì `mbasic` là login
            # wall (task.md I-14, I-22).
            if playwright_enabled:
                await playwright_dom.collect(
                    target, bundle, limiter=limiter, cookie=facebook_cookie
                )
        if profile_text:
            collect_from_text(profile_text, bundle)

        avatar = await fetch_and_normalize(
            bundle, client=client, limiter=limiter, output_dir=upload_dir
        )
        # Ảnh công khai (task X.1): đề bài §1 nêu đích danh "ảnh đại diện **hoặc
        # hình ảnh công khai gần nhất**", và đo thật cho thấy Facebook khoá chữ
        # nhưng không khoá ảnh (I-30).
        public_photos = await fetch_public_photos(
            bundle, client=client, limiter=limiter, output_dir=upload_dir
        )

        # --- Profile ------------------------------------------------------
        profile = await build_profile(
            bundle, gateway, model=model, avatar=avatar, public_photos=public_photos
        )
        evidence_corpus = bundle.evidence_corpus()

        # Không có cả tên lẫn mô tả ảnh → mọi tin nhắn sẽ là lời chung chung.
        # Dừng ở đây và nói thật, thay vì sinh nội dung vô căn cứ (luật L1).
        if not profile.is_usable_for_rapport:
            return AnalysisOutcome(
                output=StrictOutput(
                    status=profile.status,
                    facebook_url=facebook_url,
                    profile_data=_profile_data_model(profile),
                    error_note=(
                        profile.error_note or "Không đọc được dữ kiện nào nên không sinh nội dung."
                    ),
                ),
                bundle=bundle,
                profile=profile,
                layers_used=bundle.layers_used,
            )

        # --- Chuỗi tin nhắn + kiểm duyệt ----------------------------------
        sequence = await generate_validated_sequence(
            profile,
            evidence_corpus,
            gateway,
            model=model,
            n_messages=n_messages,
            temperature=temperature,
        )

        # --- Hook 20h -----------------------------------------------------
        hook = await generate_evening_hook(
            profile,
            evidence_corpus,
            gateway,
            model=model,
            empathy_angle=sequence.empathy_angle,
            recent_hooks=recent_hooks,
            temperature=temperature,
        )

        status, error_note = _resolve_status(profile, sequence, hook)

        output = StrictOutput(
            status=status,
            facebook_url=facebook_url,
            profile_data=_profile_data_model(profile),
            ethical_rapport=EthicalRapport(
                core_empathy_angle=sequence.empathy_angle,
                dialogue_sequence_10=sequence.messages,
                sales_mention_check=sequence.sales_check,
            ),
            evening_cadence_20pm=EveningCadence(evening_hook_message=hook.message),
            error_note=error_note,
        )
        return AnalysisOutcome(
            output=output,
            bundle=bundle,
            profile=profile,
            sequence=sequence,
            hook=hook,
            layers_used=bundle.layers_used,
        )
    finally:
        if owns_client:
            await client.aclose()


def _violation_summary(sequence: ValidatedSequence) -> str:
    """Tóm tắt **loại** vi phạm, không trích nội dung vi phạm."""
    kinds: list[str] = []
    if sequence.grounding_report and not sequence.grounding_report.passed:
        kinds.append("nhắc dữ kiện không có bằng chứng")
    if sequence.sales_report and not sequence.sales_report.passed:
        kinds.append("có dấu hiệu chào bán")
    if sequence.rapport and sequence.rapport.style_issues:
        kinds.append("sai ràng buộc văn phong")
    return ", ".join(kinds) or "không rõ nguyên nhân"


def _profile_data_model(profile: ProfileResult) -> ProfileData:
    return ProfileData(
        customer_name=profile.customer_name,
        visual_context=profile.visual_context,
        estimated_demographics=EstimatedDemographics(**profile.demographics.to_output_dict()),
    )


def _resolve_status(
    profile: ProfileResult,
    sequence: ValidatedSequence,
    hook: EveningHookResult,
) -> tuple[str, str | None]:
    """Gộp status của ba bước thành một.

    Kiểm duyệt fail **thắng** mọi thứ khác: chuỗi tin nhắn là sản phẩm chính,
    thiếu nó mà gọi là `SUCCESS` thì là nói dối.
    """
    notes: list[str] = []
    if profile.error_note:
        notes.append(profile.error_note)

    if not sequence.passed:
        # Nêu **loại** vi phạm, tuyệt đối không trích nguyên văn câu vi phạm.
        #
        # Đã gặp thật (task.md I-23): đưa `rejected_reasons` vào `error_note`
        # kéo luôn câu chào bán ("…Dr.Bee…giá chỉ 299k…") trở lại output —
        # người vận hành copy từ đó đi gửi là xong, luật L2 thành vô nghĩa.
        # Chi tiết đầy đủ vẫn nằm ở `rapport_runs.grounding_report` để truy vết.
        notes.append(
            "Chuỗi tin nhắn không qua được kiểm duyệt sau "
            f"{sequence.attempts} lượt nên không trả nội dung "
            f"({_violation_summary(sequence)})."
        )
        return STATUS_FAILED_VALIDATION, " ".join(notes)

    if not hook.passed:
        notes.append(
            f"Hook 20h không qua được kiểm duyệt sau {hook.attempts} lượt "
            "nên evening_hook_message để trống."
        )
        return STATUS_FAILED_VALIDATION, " ".join(notes)

    return profile.status, profile.error_note
