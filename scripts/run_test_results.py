"""Chạy CLI trên 3 link Facebook thật rồi gộp vào `test_results.json` (task.md D2.14).

Chạy **từ host**, nhưng gọi `main.py` **bên trong container** api — để kết quả
phản ánh đúng môi trường production (cùng phiên bản thư viện, cùng đường mạng
ra ngoài, cùng cấu hình), trong khi script vẫn nằm ngoài image:

    python scripts/run_test_results.py

Hai điều script này **không** làm, có chủ đích:

- **Không lọc kết quả.** `FAILED_VALIDATION` và `PARTIAL_OR_PRIVATE` được ghi
  nguyên vẹn. Chỉ giữ lại ca đẹp là biến bằng chứng thành quảng cáo — mà đề bài
  tính điểm chính ở chỗ hệ thống dám nói "không đọc được".
- **Không chạm vào secret.** Mỗi lần chạy chỉ ghi `provider`/`model`/thời lượng;
  cookie và token không đi qua đây.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time
from datetime import UTC, datetime

#: Ba link do **người dùng cung cấp** (task.md D2.14 bắt buộc hỏi, không tự chọn).
#: Link thứ ba cố ý không tồn tại — nó minh chứng nhánh không-đọc-được, và một
#: bộ test chỉ toàn ca đẹp thì không chứng minh được tính trung thực.
LINKS = [
    "https://www.facebook.com/vander.374801",
    "https://www.facebook.com/yazawanico24111",
    "https://www.facebook.com/trang.khong.ton.tai.de.kiem.chung.2026",
]

OUT = pathlib.Path("test_results.json")

#: Khoá tuyệt đối không được xuất hiện trong file kết quả.
FORBIDDEN_KEYS = {"cookie", "token", "api_key", "secret", "password", "authorization"}


def run_one(url: str, *, provider: str, model: str) -> dict:
    started = time.monotonic()
    # `-T` tắt cấp phát TTY: thiếu nó, Docker trộn ký tự điều khiển vào stdout
    # và JSON hết parse được — đúng kiểu lỗi làm người ta nghi oan cho CLI.
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "python",
            "main.py",
            "--url",
            url,
            "--no-db",
            "--provider",
            provider,
            "--model",
            model,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    duration_ms = int((time.monotonic() - started) * 1000)

    # Hợp đồng của CLI: stdout **chỉ** có một chuỗi JSON, mọi nhánh đều hợp lệ.
    # Nếu điều đó vỡ thì chính nó là phát hiện cần ghi lại, không phải che đi.
    try:
        output = json.loads(proc.stdout)
        parse_error = None
    except json.JSONDecodeError as exc:
        output = None
        parse_error = f"stdout không phải JSON hợp lệ: {exc}"

    return {
        "facebook_url": url,
        "duration_ms": duration_ms,
        "exit_code": proc.returncode,
        "stdout_is_valid_json": parse_error is None,
        "parse_error": parse_error,
        "output": output,
    }


def assert_no_secret(payload: object, path: str = "") -> None:
    """Chặn secret lọt vào file nộp. Quét **đệ quy**, không chỉ tầng trên cùng."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if any(bad in key.lower() for bad in FORBIDDEN_KEYS):
                raise SystemExit(f"DỪNG: khoá nghi là secret tại {path}/{key}")
            assert_no_secret(value, f"{path}/{key}")
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            assert_no_secret(item, f"{path}[{i}]")


def active_gateway() -> tuple[str, str]:
    """Cổng và model **đang được chọn thật**, hỏi thẳng API đang chạy.

    Không nhận từ biến môi trường làm đường chính: giá trị gõ tay rất dễ lệch
    với cấu hình thật, và khi ấy `test_results.json` ghi một model mà lần chạy
    không hề dùng — tức bằng chứng nói sai.
    """
    import urllib.request

    with urllib.request.urlopen("http://localhost:8000/api/llm/status", timeout=10) as resp:
        status = json.loads(resp.read())

    provider, model = status.get("provider"), status.get("model")
    if not provider or not model:
        raise SystemExit(
            "DỪNG: chưa chọn cổng/model. Vào http://localhost:5173/cai-dat chọn trước khi chạy."
        )
    return provider, model


def main() -> None:
    provider, model = active_gateway()
    print(f"Cổng đang dùng: {provider} / {model}", file=sys.stderr)

    runs = []
    for i, url in enumerate(LINKS, 1):
        print(f"[{i}/{len(LINKS)}] {url}", file=sys.stderr, flush=True)
        record = run_one(url, provider=provider, model=model)
        status = (record["output"] or {}).get("status", "?")
        print(f"    -> {status} ({record['duration_ms']} ms)", file=sys.stderr, flush=True)
        runs.append(record)

    summary: dict[str, int] = {}
    for record in runs:
        status = (record["output"] or {}).get("status", "KHONG_PARSE_DUOC")
        summary[status] = summary.get(status, 0) + 1

    document = {
        "run_at": datetime.now(UTC).isoformat(),
        "provider": provider,
        "model": model,
        "total_links": len(LINKS),
        "status_summary": summary,
        "runs": runs,
    }

    assert_no_secret(document)
    OUT.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã ghi {OUT} — {summary}", file=sys.stderr)


if __name__ == "__main__":
    main()
