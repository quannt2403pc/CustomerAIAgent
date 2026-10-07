"""CLI — `python main.py --url "https://www.facebook.com/<user>"`.

Hợp đồng của file này (plan.md §5.7, §5.8):

- **stdout chỉ có đúng một chuỗi JSON.** Mọi log đi stderr (`app/core/logging`),
  nên `python main.py --url … > output.json` luôn ra file parse được.
- **Mọi nhánh đều in JSON hợp lệ** — kể cả lỗi không lường trước. Script gọi CLI
  không bao giờ phải xử lý "không có output".
- Exit code: `0` cho `SUCCESS`/`PARTIAL_OR_PRIVATE`, `1` cho
  `ERROR`/`FAILED_VALIDATION`. `PARTIAL_OR_PRIVATE` **là kết quả đạt** (đề bài
  §4) nên không trả mã lỗi.

Ví dụ:

    python main.py --url "https://www.facebook.com/example_user"
    python main.py --url "..." --provider google_api_key --model gemini-x
    python main.py --profile-file samples/pasted_profile.txt   # không cần mạng
    python main.py --url "..." --no-db --out output.json
    python main.py --url "..." --mask-pii
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys

# Hai lời gọi dưới đây phải chạy TRƯỚC mọi thứ khác, mỗi cái vì một lý do riêng:
#
#   - policy event loop: trước khi loop đầu tiên được tạo (task.md I-04)
#   - UTF-8 cho stdio:   trước lần ghi stdout/stderr đầu tiên (task.md I-61) —
#     console Windows mặc định cp1252, và `--help` lẫn JSON đầu ra đều nổ
from app.core.eventloop import ensure_compatible_event_loop_policy
from app.core.stdio import force_utf8_stdio

force_utf8_stdio()
ensure_compatible_event_loop_policy()

from app.core.config import ConfigError, get_settings  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.core.logging import get_logger, setup_logging  # noqa: E402
from app.schemas.output import StrictOutput, write_output_json  # noqa: E402

log = get_logger("main")

DEFAULT_OUT = "output.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description="Cỗ máy AI Profiler & Rapport — phân tích một trang Facebook công khai.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--url", help="URL trang cá nhân Facebook công khai")
    parser.add_argument(
        "--profile-file",
        help="Tệp văn bản người vận hành dán tay (đường L4, chạy được khi không có mạng)",
    )
    parser.add_argument(
        "--provider",
        choices=["antigravity", "google_api_key"],
        help="Ghi đè cổng model đang chọn trong DB",
    )
    parser.add_argument("--model", help="Ghi đè model đang chọn (phải có trong danh mục cổng)")
    parser.add_argument(
        "--out", default=DEFAULT_OUT, help=f"Tệp JSON đầu ra (mặc định {DEFAULT_OUT})"
    )
    parser.add_argument(
        "--messages",
        type=int,
        help="Số tin nhắn tâm sự, 5–10 (mặc định 10 theo đề bài)",
    )
    parser.add_argument(
        "--no-db", action="store_true", help="Không ghi PostgreSQL, chỉ in JSON và ghi tệp"
    )
    parser.add_argument(
        "--mask-pii", action="store_true", help="Che tên và URL trong output để chia sẻ rộng"
    )
    parser.add_argument(
        "--fb-cookie-file",
        help=(
            "Tệp chứa cookie Facebook của CHÍNH BẠN (task X.2). Mở khoá phần chữ "
            "— bài viết Công khai vẫn bị che với khách chưa đăng nhập. "
            "RỦI RO: Facebook có thể khoá tài khoản bị dùng để truy cập tự động."
        ),
    )
    parser.add_argument("--log-level", help="Ghi đè LOG_LEVEL")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    settings = get_settings()
    setup_logging(args.log_level or settings.log_level, force=True)

    if not args.url and not args.profile_file:
        # Lỗi dùng sai CLI → vẫn in JSON hợp lệ để script gọi không phải phân nhánh.
        return _emit(
            StrictOutput(
                status="ERROR",
                facebook_url="",
                error_note="Thiếu đầu vào: cần --url hoặc --profile-file.",
            ),
            out_path=args.out,
            mask_pii=args.mask_pii,
        )

    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:  # pragma: no cover — phụ thuộc người dùng
        return _emit(
            StrictOutput(
                status="ERROR",
                facebook_url=args.url or "",
                error_note="Người dùng đã dừng chương trình.",
            ),
            out_path=args.out,
            mask_pii=args.mask_pii,
        )


async def _run(args: argparse.Namespace) -> int:
    from app.services.pipeline import run_analysis

    profile_text = _read_profile_file(args.profile_file) if args.profile_file else None

    gateway = None
    session_ctx = None
    try:
        gateway, provider, model, session_ctx = await _open_gateway(args)
    except (AppError, ConfigError) as exc:
        return _emit(
            StrictOutput(
                status="ERROR",
                facebook_url=args.url or "",
                error_note=_message_of(exc),
            ),
            out_path=args.out,
            mask_pii=args.mask_pii,
        )
    except Exception as exc:
        # Bắt rộng ở đây là **cố ý**. Lỗi hạ tầng không phải `AppError` —
        # ví dụ Postgres không phân giải được tên host `db` khi chạy ngoài
        # Docker — mà để nó thoát ra thì CLI **không in JSON nào**, phá đúng
        # hợp đồng chính của file này.
        log.exception("Không mở được cổng model / kết nối database")
        return _emit(
            StrictOutput(
                status="ERROR",
                facebook_url=args.url or "",
                error_note=_setup_failure_note(exc),
            ),
            out_path=args.out,
            mask_pii=args.mask_pii,
        )

    try:
        outcome = await run_analysis(
            gateway=gateway,
            model=model,
            url=args.url,
            profile_text=profile_text,
            n_messages=args.messages,
            temperature=get_settings().llm_temperature,
            playwright_enabled=get_settings().playwright_enabled,
            facebook_cookie=await _resolve_cookie(args, session_ctx),
        )
    except AppError as exc:
        log.error("Phân tích thất bại: %s", exc.code)
        return _emit(
            StrictOutput(status="ERROR", facebook_url=args.url or "", error_note=_message_of(exc)),
            out_path=args.out,
            mask_pii=args.mask_pii,
        )
    except Exception as exc:  # mọi lỗi vẫn phải ra JSON hợp lệ
        log.exception("Lỗi không lường trước")
        return _emit(
            StrictOutput(
                status="ERROR",
                facebook_url=args.url or "",
                error_note=f"Lỗi không lường trước: {type(exc).__name__}.",
            ),
            out_path=args.out,
            mask_pii=args.mask_pii,
        )
    finally:
        if gateway is not None:
            await gateway.aclose()

    if session_ctx is not None:
        await _save(session_ctx, outcome, provider=provider, model=model)

    return _emit(outcome.output, out_path=args.out, mask_pii=args.mask_pii)


async def _open_gateway(args: argparse.Namespace):
    """Dựng gateway + xác định model. Trả `(gateway, provider, model, session_ctx)`.

    `session_ctx` là `None` khi `--no-db`: đường L4 phải chạy được mà không cần
    Postgres (task.md D1.12).
    """
    settings = get_settings()

    if args.no_db:
        gateway = _gateway_without_db(args.provider or settings.llm_provider)
        model = _require_model(args.model or settings.llm_model, gateway.provider)
        return gateway, gateway.provider, model, None

    from app.db.engine import get_sessionmaker
    from app.llm.resolver import get_active_config, resolve_gateway

    session = get_sessionmaker()()
    config = await get_active_config(session)
    gateway = await resolve_gateway(session, provider=args.provider)
    model = _require_model(args.model or config.model or settings.llm_model, gateway.provider)
    await session.commit()
    return gateway, gateway.provider, model, session


def _gateway_without_db(provider: str):
    """Dựng gateway không qua DB — credential lấy từ `.env`."""
    from app.core.errors import GatewayNoCredential, GatewayNotConfigured
    from app.llm.antigravity import AntigravityGateway
    from app.llm.google_api_key import GoogleApiKeyGateway

    settings = get_settings()
    if not provider:
        raise GatewayNotConfigured(
            "Chạy --no-db thì phải nêu cổng: --provider antigravity|google_api_key "
            "(hoặc đặt LLM_PROVIDER trong .env)."
        )
    if provider == "antigravity":
        return AntigravityGateway(settings)
    key = settings.google_api_key.strip()
    if not key:
        raise GatewayNoCredential(
            "Chạy --no-db với cổng google_api_key thì cần GOOGLE_API_KEY trong .env."
        )
    return GoogleApiKeyGateway(key, settings)


def _require_model(model: str | None, provider: str) -> str:
    """Không có model → lỗi rõ ràng.

    Luật L6: **không** có model mặc định trong source. Danh mục đến từ cổng lúc
    chạy, nên chỉ người dùng mới biết chọn gì.
    """
    from app.core.errors import GatewayModelInvalid

    if model and model.strip():
        return model.strip()
    raise GatewayModelInvalid(
        f"Chưa chọn model cho cổng `{provider}`. Dùng --model <tên>, hoặc chọn trên "
        "trang Cài đặt, hoặc đặt LLM_MODEL trong .env. Danh mục model lấy từ cổng "
        "lúc chạy nên không có giá trị mặc định."
    )


async def _save(session, outcome, *, provider: str, model: str) -> None:
    """Ghi DB. Lỗi DB **không** được làm mất output đã sinh."""
    from app.services.persistence import save_analysis

    try:
        await save_analysis(session, outcome, provider=provider, model=model)
        await session.commit()
    except Exception:  # JSON đã sinh xong, đừng đánh mất nó
        log.exception("Không ghi được kết quả vào database")
        await session.rollback()
    finally:
        await session.close()


async def _resolve_cookie(args: argparse.Namespace, session) -> str | None:
    """Cookie Facebook theo thứ tự: cờ dòng lệnh → DB (đã mã hoá) → `.env`.

    Cờ đứng trước để người vận hành ghi đè được mà không phải sửa cấu hình đã
    lưu. Cookie hỏng/thiếu field → **cảnh báo rồi đi tiếp không cookie**, chứ
    không làm hỏng cả lượt chạy: thiếu cookie chỉ nghĩa là đọc được ít hơn.
    """
    from app.collectors import facebook_cookie as fb
    from app.core.errors import CollectorError

    raw: str | None = None
    if args.fb_cookie_file:
        raw = pathlib.Path(args.fb_cookie_file).read_text(encoding="utf-8")
    elif session is not None:
        from app.services import credentials

        raw = await credentials.get_secret(session, credentials.KIND_FB_COOKIE)
    if not raw:
        raw = get_settings().facebook_cookie

    if not raw or not raw.strip():
        return None

    try:
        info = fb.validate(raw)
    except CollectorError as exc:
        log.warning("Bỏ qua cookie Facebook: %s", exc.message)
        return None

    log.info("Dùng cookie Facebook của tài khoản %s", info.masked_account)
    return fb.to_header(raw)


def _read_profile_file(path: str) -> str:
    content = pathlib.Path(path).read_text(encoding="utf-8")
    if not content.strip():
        log.warning("Tệp %s rỗng", path)
    return content


def _message_of(exc: Exception) -> str:
    return exc.message if isinstance(exc, AppError) else str(exc)


def _setup_failure_note(exc: Exception) -> str:
    """Câu tiếng Việt cho lỗi hạ tầng lúc khởi tạo — nói đúng việc cần làm.

    Nhận dạng riêng lỗi "không tới được database" vì đó là tình huống hay gặp
    nhất: `.env` trỏ `DATABASE_URL` vào host `db` của Docker, nên chạy CLI
    ngoài Docker sẽ không phân giải được tên đó.
    """
    from sqlalchemy.exc import SQLAlchemyError

    if isinstance(exc, SQLAlchemyError):
        return (
            "Không kết nối được database. Nếu bạn chạy CLI ngoài Docker, hãy thêm "
            "--no-db (chỉ in JSON và ghi tệp), hoặc sửa DATABASE_URL trong .env "
            "trỏ về 127.0.0.1 thay vì tên host `db` của Docker."
        )
    return f"Không khởi tạo được phiên làm việc: {type(exc).__name__}."


def _emit(output: StrictOutput, *, out_path: str, mask_pii: bool) -> int:
    """In JSON ra **stdout** và ghi ra tệp. Đây là chỗ duy nhất chạm stdout."""
    final = output.masked() if mask_pii else output
    text = final.to_json()

    try:
        write_output_json(final, out_path)
    except OSError as exc:
        # Không ghi được tệp thì vẫn phải in JSON — stdout là hợp đồng chính.
        log.error("Không ghi được %s: %s", out_path, exc.strerror)

    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    return final.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
