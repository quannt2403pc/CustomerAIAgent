"""Đo a11y + responsive bằng Playwright + axe-core (task.md D2.11).

    python scripts/audit_a11y.py

Vì sao phải dùng Playwright chứ không "chỉnh cửa sổ rồi nhìn": đo thật ở lần
trước cho thấy đổi kích thước cửa sổ **không** đổi viewport mà JS nhìn thấy
(`innerWidth` giữ nguyên 1536), nên mọi kết luận "responsive ổn" rút ra từ đó
đều vô giá trị. Playwright đặt viewport thật.

Ba thứ được đo, và lý do từng thứ:

1. **axe-core** — bắt vi phạm WCAG máy kiểm được. Chỉ chặn ở mức
   `serious`/`critical`; `minor`/`moderate` vẫn in ra để biết, nhưng không làm
   hỏng kết quả, vì chúng thường là đánh đổi thiết kế có chủ đích.
2. **Tràn ngang** — `scrollWidth > clientWidth` ở viewport hẹp. Đây là lỗi
   responsive hay bị bỏ sót nhất: trang vẫn "trông ổn" nhưng người dùng phải kéo
   ngang để đọc hết một dòng.
3. **Vùng bấm < 24px** — ngưỡng WCAG 2.5.8 (AA). plan.md §6.2 đặt mục tiêu 44px
   nhưng đó là mục tiêu thiết kế; 24px mới là mức *vi phạm chuẩn*. Đo cả hai để
   phân biệt "chưa đẹp" với "sai chuẩn".
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

AXE_PATH = pathlib.Path("web/node_modules/axe-core/axe.min.js")

BASE = "http://localhost:5173"

PAGES = {
    "Dashboard": "/",
    "Phân tích": "/phan-tich",
    "Hội thoại": "/hoi-thoai",
    "Outbox": "/outbox",
    "Cài đặt": "/cai-dat",
}

#: Bốn mốc trong DoD. 375 = iPhone SE, mốc hẹp nhất còn đáng hỗ trợ.
VIEWPORTS = [(375, 812), (768, 1024), (1024, 768), (1440, 900)]

#: WCAG 2.5.8 (AA) — dưới mức này là **vi phạm chuẩn**, không phải góp ý.
MIN_TARGET_WCAG = 24
#: Mục tiêu thiết kế của plan.md §6.2.
TARGET_GOAL = 44

COUNT_SCRIPT = """
() => {
  const doc = document.documentElement;
  const els = [...document.querySelectorAll(
    'button, a[href], input, select, textarea, [role="button"], [tabindex]:not([tabindex="-1"])'
  )];

  // Ba loại được MIỄN, theo đúng ngoại lệ của WCAG 2.5.8 — không phải để test
  // dễ xanh, mà vì tính chúng vào là đo sai bản chất:
  //
  //   1. Phần tử ẩn tới khi focus (skip link). Nó không phải đích con trỏ;
  //      lúc focus nó hiện ra đủ lớn.
  //   2. Liên kết nằm TRONG một câu văn — ngoại lệ "inline" ghi thẳng trong
  //      tiêu chuẩn. Ép 24px cho chữ trong câu sẽ phá vỡ chính dòng chữ đó.
  //   3. Control có <label> bao quanh. Vùng bấm thật là cả cái label; đo riêng
  //      ô checkbox 13×16 rồi kết luận vi phạm là đo nhầm đối tượng.
  const INLINE_PARENTS = new Set(['P', 'LI', 'SPAN', 'TD', 'LABEL', 'STRONG', 'EM', 'SMALL']);

  const small = [];
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') continue;

    // (1) Ẩn bằng kỹ thuật sr-only/clip — chỉ hiện khi focus.
    if (r.width <= 2 && r.height <= 2) continue;

    let w = r.width, h = r.height;

    // (3) Label bao quanh mở rộng vùng bấm.
    const label = el.closest('label');
    if (label && label !== el) {
      const lr = label.getBoundingClientRect();
      w = Math.max(w, lr.width);
      h = Math.max(h, lr.height);
    }

    // Vùng ::after nới ra (xem button.tsx) cũng là vùng bấm thật.
    const after = getComputedStyle(el, '::after');
    if (after && after.content && after.content !== 'none' && after.position === 'absolute') {
      const top = parseFloat(after.top) || 0, bottom = parseFloat(after.bottom) || 0;
      const left = parseFloat(after.left) || 0, right = parseFloat(after.right) || 0;
      h += Math.max(0, -top) + Math.max(0, -bottom);
      w += Math.max(0, -left) + Math.max(0, -right);
    }

    // (2) Liên kết chữ nằm trong câu văn.
    const inline = el.tagName === 'A'
      && el.parentElement
      && INLINE_PARENTS.has(el.parentElement.tagName)
      && style.display.startsWith('inline');

    small.push({
      tag: el.tagName.toLowerCase(),
      label: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 40),
      w: Math.round(w), h: Math.round(h),
      inlineExempt: Boolean(inline),
    });
  }
  return {
    scrollWidth: doc.scrollWidth,
    clientWidth: doc.clientWidth,
    targets: small,
  };
}
"""


async def main() -> None:
    from playwright.async_api import async_playwright

    if not AXE_PATH.exists():
        raise SystemExit(f"DỪNG: không thấy {AXE_PATH}. Chạy `npm install` trong web/ trước.")
    axe_source = AXE_PATH.read_text(encoding="utf-8")

    report: dict = {"pages": {}, "summary": {}}
    blocking = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            for name, path in PAGES.items():
                report["pages"][name] = {}
                for width, height in VIEWPORTS:
                    context = await browser.new_context(viewport={"width": width, "height": height})
                    page = await context.new_page()
                    await page.goto(f"{BASE}{path}", wait_until="networkidle")

                    # `evaluate` chứ KHÔNG `add_script_tag`: CSP của trang là
                    # `script-src 'self'`, nên chèn thẻ script inline bị chặn —
                    # và việc nó bị chặn chính là bằng chứng CSP đang có hiệu
                    # lực thật. `evaluate` đi qua CDP nên không vướng CSP, mà
                    # cũng không cần nới lỏng chính sách chỉ để đo được.
                    await page.evaluate(axe_source)
                    axe = await page.evaluate("async () => await axe.run()")
                    metrics = await page.evaluate(COUNT_SCRIPT)

                    counts: dict[str, int] = {}
                    serious: list[str] = []
                    for v in axe["violations"]:
                        impact = v.get("impact") or "unknown"
                        counts[impact] = counts.get(impact, 0) + 1
                        if impact in ("serious", "critical"):
                            serious.append(f"{v['id']} ({len(v['nodes'])} chỗ)")

                    overflow = metrics["scrollWidth"] > metrics["clientWidth"]
                    under_wcag = [
                        t
                        for t in metrics["targets"]
                        if min(t["w"], t["h"]) < MIN_TARGET_WCAG and not t["inlineExempt"]
                    ]
                    under_goal = [
                        t for t in metrics["targets"] if min(t["w"], t["h"]) < TARGET_GOAL
                    ]

                    if serious or overflow or under_wcag:
                        blocking += 1

                    report["pages"][name][f"{width}x{height}"] = {
                        "axe_violations_by_impact": counts,
                        "serious_or_critical": serious,
                        "horizontal_overflow": overflow,
                        "scroll_width": metrics["scrollWidth"],
                        "client_width": metrics["clientWidth"],
                        "targets_under_wcag_24px": under_wcag,
                        "targets_under_goal_44px_count": len(under_goal),
                    }

                    flag = "FAIL" if (serious or overflow or under_wcag) else "ok  "
                    print(
                        f"  {flag} {name:<12} {width}x{height:<5} "
                        f"axe={counts or '{}'} tràn={overflow} "
                        f"<24px={len(under_wcag)} <44px={len(under_goal)}",
                        file=sys.stderr,
                        flush=True,
                    )

                    await context.close()
        finally:
            await browser.close()

    report["summary"] = {
        "total_checks": len(PAGES) * len(VIEWPORTS),
        "blocking_checks": blocking,
        "passed": blocking == 0,
    }

    out = pathlib.Path("var/a11y_report.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nĐã ghi {out} — blocking={blocking}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
