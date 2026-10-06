"""Tải + chuẩn hoá ảnh đại diện (plan.md §5.3, task.md D1.14).

Chuẩn hoá về **WebP ≤1024px** trước khi gửi lên model vì ba lý do cụ thể:
ảnh gốc của Facebook CDN có thể vài MB (tốn token và thời gian), `inline_data`
của Gemini có giới hạn kích thước, và WebP giữ chất lượng tốt hơn JPEG ở cùng
dung lượng nên mô tả vision chính xác hơn.

Không tải được → **không raise**: `visual_context` sẽ là `null` và status hạ
xuống `PARTIAL_OR_PRIVATE`. Thà thiếu còn hơn bịa (luật L1).
"""

from __future__ import annotations

import hashlib
import io
import pathlib

import httpx
from PIL import Image, UnidentifiedImageError

from app.collectors.evidence import CollectAttempt, EvidenceBundle, EvidenceImage
from app.collectors.og_meta import build_headers
from app.collectors.throttle import HostRateLimiter
from app.core.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

LAYER = "avatar"
PHOTOS_LAYER = "public_photos"

MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024
MAX_EDGE_PX = 1024
WEBP_QUALITY = 82
OUTPUT_MIME = "image/webp"

# Whitelist theo nội dung thật, không theo đuôi file hay Content-Type khai báo.
ALLOWED_PILLOW_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP"}


class NormalizedImage:
    """Ảnh đã chuẩn hoá, sẵn sàng nhúng `inline_data`."""

    __slots__ = ("data", "height", "local_path", "mime_type", "role", "sha256", "width")

    def __init__(
        self,
        data: bytes,
        *,
        mime_type: str,
        width: int,
        height: int,
        sha256: str,
        local_path: str | None = None,
        role: str = "avatar",
    ):
        self.data = data
        self.mime_type = mime_type
        self.width = width
        self.height = height
        self.sha256 = sha256
        self.local_path = local_path
        self.role = role

    def __repr__(self) -> str:  # pragma: no cover — chỉ để debug
        return (
            f"NormalizedImage({self.role}, {self.width}x{self.height}, "
            f"{len(self.data)}B, {self.mime_type}, sha256={self.sha256[:12]}…)"
        )


#: Tên cũ, giữ lại cho code đã viết trước task X.1.
NormalizedAvatar = NormalizedImage


async def fetch_and_normalize(
    bundle: EvidenceBundle,
    *,
    client: httpx.AsyncClient | None = None,
    limiter: HostRateLimiter | None = None,
    output_dir: str | None = None,
) -> NormalizedImage | None:
    """Tải avatar trong `bundle` rồi chuẩn hoá. `None` nếu không có/không được.

    Mọi thất bại được ghi vào `attempts[]` thay vì raise — tầng trên dựa vào đó
    để hạ status và viết `error_note` trung thực.
    """
    image_ref = bundle.avatar
    if image_ref is None:
        bundle.add_attempt(
            CollectAttempt(layer=LAYER, ok=False, skipped=True, note="không có URL ảnh đại diện")
        )
        return None

    # Ảnh người vận hành tải lên đã nằm trên đĩa — đọc trực tiếp, không gọi mạng.
    if image_ref.local_path:
        try:
            raw = pathlib.Path(image_ref.local_path).read_bytes()
        except OSError as exc:
            bundle.add_attempt(
                CollectAttempt(layer=LAYER, ok=False, note=f"không đọc được tệp: {exc.strerror}")
            )
            return None
        return _normalize_and_record(raw, bundle, image_ref, output_dir=output_dir)

    settings = get_settings()
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(settings.collector_timeout_seconds), follow_redirects=True
    )
    source_url = _best_source_url(bundle, image_ref)
    try:
        if limiter is not None:
            await limiter.wait(source_url)
        try:
            response = await client.get(source_url, headers=build_headers())
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            bundle.add_attempt(
                CollectAttempt(layer=LAYER, ok=False, note=f"lỗi mạng: {type(exc).__name__}")
            )
            return None

        if response.status_code >= 400:
            bundle.add_attempt(
                CollectAttempt(layer=LAYER, ok=False, http_status=response.status_code)
            )
            return None

        raw = response.content
        if len(raw) > MAX_DOWNLOAD_BYTES:
            bundle.add_attempt(
                CollectAttempt(
                    layer=LAYER,
                    ok=False,
                    http_status=response.status_code,
                    note=f"ảnh {len(raw) // 1024}KB vượt giới hạn "
                    f"{MAX_DOWNLOAD_BYTES // (1024 * 1024)}MB",
                )
            )
            return None

        return _normalize_and_record(
            raw, bundle, image_ref, http_status=response.status_code, output_dir=output_dir
        )
    finally:
        if owns_client:
            await client.aclose()


async def fetch_public_photos(
    bundle: EvidenceBundle,
    *,
    client: httpx.AsyncClient | None = None,
    limiter: HostRateLimiter | None = None,
    output_dir: str | None = None,
    limit: int = 3,
) -> list[NormalizedImage]:
    """Tải + chuẩn hoá các ảnh công khai trong `bundle` (task X.1).

    Đề bài §1 nêu đích danh "ảnh đại diện **hoặc hình ảnh công khai gần nhất**".
    Đo thật (I-30): Facebook khoá phần chữ nhưng vẫn phục vụ lưới ảnh, nên đây
    là nguồn evidence mạnh nhất lấy được mà không cần đăng nhập.

    Ảnh nào tải/giải mã không được thì **bỏ qua ảnh đó**, không bỏ cả lượt:
    một ảnh hỏng không nên làm mất ba ảnh còn lại.
    """
    avatar_key = _photo_key(bundle.avatar.url) if bundle.avatar else None
    refs = [
        image
        for image in bundle.images
        # Lưới ảnh chứa **cả** ảnh đại diện, chỉ khác tham số crop. Gửi nó hai
        # lần cho model là tốn ~1500 token prompt mà không thêm thông tin nào.
        if image.role == "public_photo" and _photo_key(image.url) != avatar_key
    ][:limit]
    if not refs:
        return []

    settings = get_settings()
    owns_client = client is None
    client = client or httpx.AsyncClient(
        timeout=httpx.Timeout(settings.collector_timeout_seconds), follow_redirects=True
    )
    # Giữ cặp (ref, ảnh) chứ không hai danh sách song song: ảnh nào tải hỏng thì
    # bị bỏ qua, nên `zip` hai danh sách sẽ gắn sha256 vào **nhầm** URL.
    pairs: list[tuple[EvidenceImage, NormalizedImage]] = []
    failed = 0

    try:
        for ref in refs:
            if limiter is not None:
                await limiter.wait(ref.url)
            try:
                response = await client.get(ref.url, headers=build_headers())
            except (httpx.TimeoutException, httpx.TransportError):
                failed += 1
                continue

            if response.status_code >= 400 or len(response.content) > MAX_DOWNLOAD_BYTES:
                failed += 1
                continue

            try:
                image = normalize(response.content)
            except ValueError:
                failed += 1
                continue

            image.role = "public_photo"
            image.local_path = _write_to_disk(image, output_dir)
            pairs.append((ref, image))
    finally:
        if owns_client:
            await client.aclose()

    _record_photo_urls(bundle, pairs)
    bundle.add_attempt(
        CollectAttempt(
            layer=PHOTOS_LAYER,
            ok=bool(pairs),
            note=(
                f"{len(pairs)} ảnh công khai đã chuẩn hoá"
                + (f", {failed} ảnh bỏ qua vì không tải/đọc được" if failed else "")
            ),
        )
    )
    return [image for _, image in pairs]


def _record_photo_urls(
    bundle: EvidenceBundle, pairs: list[tuple[EvidenceImage, NormalizedImage]]
) -> None:
    """Gắn `sha256` + đường dẫn vào `bundle.images` — đó là bằng chứng của mô tả."""
    by_url = {ref.url: image for ref, image in pairs}
    bundle.images = [
        EvidenceImage(
            role=existing.role,
            url=existing.url,
            local_path=by_url[existing.url].local_path
            if existing.url in by_url
            else existing.local_path,
            sha256=by_url[existing.url].sha256 if existing.url in by_url else existing.sha256,
        )
        for existing in bundle.images
    ]


def _photo_key(url: str) -> str:
    """Định danh một **tấm ảnh**, bỏ qua tham số kích thước/crop.

    Facebook phục vụ cùng một ảnh ở nhiều biến thể: `og:image` là bản đã crop
    nhỏ (`?cstp=mx292x173`), còn bản trong lưới là bản đầy đủ hơn. Cùng đường
    dẫn, khác query → so theo đường dẫn mới nhận ra là một.
    """
    from urllib.parse import urlparse

    return urlparse(url).path


def _best_source_url(bundle: EvidenceBundle, image_ref: EvidenceImage) -> str:
    """URL tốt nhất cho cùng tấm ảnh đại diện.

    `og:image` là **thumbnail đã crop** (task.md I-17: đo được 292×173), trong
    khi lưới ảnh phục vụ đúng tấm đó ở 288×288 — vuông và nhiều chi tiết hơn.
    Mô tả vision dựa trên ảnh nét hơn thì chính xác hơn, nên ưu tiên bản lưới.
    """
    key = _photo_key(image_ref.url)
    for candidate in bundle.images:
        if candidate.role == "public_photo" and _photo_key(candidate.url) == key:
            log.info("Dùng bản ảnh đại diện trong lưới thay cho og:image đã crop")
            return candidate.url
    return image_ref.url


def _write_to_disk(image: NormalizedImage, output_dir: str | None) -> str:
    target_dir = pathlib.Path(output_dir or get_settings().upload_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{image.sha256}.webp"
    path.write_bytes(image.data)
    return str(path)


def normalize(raw: bytes) -> NormalizedImage:
    """Giải mã → RGB → co về ≤1024px → WebP. Raise nếu không phải ảnh hợp lệ."""
    try:
        with Image.open(io.BytesIO(raw)) as source:
            fmt = (source.format or "").upper()
            if fmt not in ALLOWED_PILLOW_FORMATS:
                raise ValueError(f"định dạng ảnh không được nhận: {fmt or 'không rõ'}")
            source.load()
            # Bỏ alpha/palette: WebP lossy cần RGB, và alpha của avatar không
            # mang thông tin gì cho bước mô tả.
            image = source.convert("RGB")
    except UnidentifiedImageError as exc:
        raise ValueError("dữ liệu tải về không phải ảnh") from exc

    image.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.Resampling.LANCZOS)

    buffer = io.BytesIO()
    image.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=4)
    data = buffer.getvalue()

    return NormalizedImage(
        data,
        mime_type=OUTPUT_MIME,
        width=image.width,
        height=image.height,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def _normalize_and_record(
    raw: bytes,
    bundle: EvidenceBundle,
    image_ref: EvidenceImage,
    *,
    http_status: int | None = None,
    output_dir: str | None = None,
) -> NormalizedImage | None:
    try:
        avatar = normalize(raw)
    except ValueError as exc:
        bundle.add_attempt(
            CollectAttempt(layer=LAYER, ok=False, http_status=http_status, note=str(exc))
        )
        return None

    path = _write_to_disk(avatar, output_dir)
    avatar.local_path = path

    # Ghi sha256 + đường dẫn vào bundle: đây là **bằng chứng** cho `visual_context`.
    bundle.images = [
        EvidenceImage(
            role=existing.role,
            url=existing.url,
            local_path=path if existing.url == image_ref.url else existing.local_path,
            sha256=avatar.sha256 if existing.url == image_ref.url else existing.sha256,
        )
        for existing in bundle.images
    ]
    bundle.add_attempt(
        CollectAttempt(
            layer=LAYER,
            ok=True,
            http_status=http_status,
            note=f"WebP {avatar.width}x{avatar.height}, {len(avatar.data) // 1024}KB",
        )
    )
    return avatar
