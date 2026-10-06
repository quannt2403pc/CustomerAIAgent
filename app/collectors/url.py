"""Chuẩn hoá URL Facebook → `url_key` (plan.md §5.2).

`url_key` là khoá định danh duy nhất của một profile. Nó phải **ổn định**: cùng
một người, dù link đến từ đâu (có `?mibextid=`, có `m.`/`web.` prefix, có dấu
`/` cuối), cũng phải cho ra một `url_key`. Không ổn định thì bảng `profiles`
đầy bản ghi trùng của cùng một người.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse, urlunparse

from app.core.errors import InvalidFacebookUrl

# Domain được chấp nhận. `fb.com`/`fb.watch` là shortlink chính thức của Facebook.
_ALLOWED_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "mbasic.facebook.com",
    "web.facebook.com",
    "touch.facebook.com",
    "d.facebook.com",
    "free.facebook.com",
    "fb.com",
    "www.fb.com",
    "fb.watch",
}

# Tham số rác do Facebook/app gắn vào khi chia sẻ — không mang thông tin định danh.
_JUNK_QUERY_KEYS = {
    "mibextid",
    "rdid",
    "sfnsn",
    "ref",
    "refid",
    "fref",
    "hc_ref",
    "comment_id",
    "notif_t",
    "notif_id",
    "share_url",
    "_rdc",
    "_rdr",
    "locale",
    "locale2",
    "paipv",
    "eav",
    "av",
    "mcache",
    "wtsid",
    "extid",
    "d",
    "vh",
    "idorvanity",
}

# Đường dẫn không phải trang cá nhân.
_NON_PROFILE_SEGMENTS = {
    "",
    "home.php",
    "login.php",
    "login",
    "checkpoint",
    "help",
    "policies",
    "privacy",
    "terms",
    "settings",
    "search",
    "watch",
    "marketplace",
    "gaming",
    "events",
    "groups",
    "pages",
    "photo.php",
    "photo",
    "story.php",
    "sharer",
    "sharer.php",
    "dialog",
    "notes",
    "reel",
    "share",
}

_USERNAME_RE = re.compile(r"^[A-Za-z0-9.\-_]{1,80}$")
_NUMERIC_ID_RE = re.compile(r"^\d{5,25}$")


@dataclass(frozen=True)
class FacebookTarget:
    """Kết quả chuẩn hoá."""

    url_key: str
    canonical_url: str
    mbasic_url: str
    kind: str  # "username" | "profile_id"
    identifier: str


def normalize_facebook_url(raw: str) -> FacebookTarget:
    """Chuẩn hoá một URL Facebook. Không phải Facebook → `InvalidFacebookUrl`.

    Nhận cả dạng thiếu scheme (`facebook.com/abc`) vì người vận hành hay copy
    link kiểu đó từ trình duyệt.
    """
    text = (raw or "").strip()
    if not text:
        raise InvalidFacebookUrl("Chưa nhập URL Facebook.")

    if "://" not in text:
        text = f"https://{text}"

    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if not host:
        raise InvalidFacebookUrl(f"URL không đọc được: {raw!r}")
    if host not in _ALLOWED_HOSTS:
        raise InvalidFacebookUrl(
            f"`{host}` không phải domain Facebook. Chỉ nhận link facebook.com / fb.com."
        )

    # `profile.php?id=…` — dạng không có username
    query = parse_qs(parsed.query)
    segments = [unquote(s) for s in parsed.path.split("/") if s]
    first = segments[0].lower() if segments else ""

    if first == "profile.php":
        profile_id = (query.get("id") or [""])[0].strip()
        if not _NUMERIC_ID_RE.match(profile_id):
            raise InvalidFacebookUrl(
                "Link `profile.php` thiếu tham số `id` hợp lệ. "
                "Hãy sao chép lại URL đầy đủ từ thanh địa chỉ."
            )
        return _build(kind="profile_id", identifier=profile_id)

    # `/people/Ten-Hien-Thi/100012345678901`
    if first == "people":
        numeric = next((s for s in reversed(segments) if _NUMERIC_ID_RE.match(s)), "")
        if not numeric:
            raise InvalidFacebookUrl(
                "Link `/people/…` thiếu ID số ở cuối. Hãy sao chép lại URL đầy đủ."
            )
        return _build(kind="profile_id", identifier=numeric)

    if not segments or first in _NON_PROFILE_SEGMENTS:
        raise InvalidFacebookUrl(
            "URL này không trỏ tới một trang cá nhân. Cần dạng "
            "`facebook.com/<username>` hoặc `facebook.com/profile.php?id=…`."
        )

    username = segments[0]
    if _NUMERIC_ID_RE.match(username):
        # `facebook.com/100012345678901` cũng là một profile hợp lệ.
        return _build(kind="profile_id", identifier=username)
    if not _USERNAME_RE.match(username):
        raise InvalidFacebookUrl(f"Username `{username}` không hợp lệ.")

    return _build(kind="username", identifier=username.lower())


def strip_junk_query(url: str) -> str:
    """Bỏ tham số rác, giữ lại tham số có nghĩa (vd `id` của `profile.php`)."""
    parsed = urlparse(url)
    kept = {
        key: values
        for key, values in parse_qs(parsed.query).items()
        if key.lower() not in _JUNK_QUERY_KEYS
    }
    query = "&".join(f"{key}={values[0]}" for key, values in sorted(kept.items()) if values)
    return urlunparse(parsed._replace(query=query, fragment=""))


def _build(*, kind: str, identifier: str) -> FacebookTarget:
    if kind == "profile_id":
        return FacebookTarget(
            url_key=f"id:{identifier}",
            canonical_url=f"https://www.facebook.com/profile.php?id={identifier}",
            mbasic_url=f"https://mbasic.facebook.com/profile.php?id={identifier}",
            kind=kind,
            identifier=identifier,
        )
    return FacebookTarget(
        url_key=f"user:{identifier}",
        canonical_url=f"https://www.facebook.com/{identifier}",
        mbasic_url=f"https://mbasic.facebook.com/{identifier}",
        kind=kind,
        identifier=identifier,
    )
