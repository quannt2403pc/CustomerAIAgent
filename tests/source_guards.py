"""Quét **code thật**, bỏ qua comment và docstring — dùng chung cho các luật thép.

Vì sao cần một bản dùng chung: hai luật được canh gác bằng cách quét source —
**L6** (không hardcode tên model) và **L3** (không có đường gửi tin nhắn). Cả hai
đều từng báo động giả vì cách quét ngây thơ:

- L6 chỉ bỏ qua dòng *bắt đầu* bằng `\"\"\"`, nên dòng **tiếp sau** của một docstring
  nhiều dòng giải thích bẫy I-10 bị báo là vi phạm.
- L3 quét cả docstring, nên chính câu "module này **không** import client
  Messenger nào" bị tính là một vi phạm.

Báo động giả làm người ta mất tin vào cái canh gác rồi tắt nó đi — tệ hơn là không
có. Hai lớp giữ hai bản quét riêng thì mỗi lần sửa chỉ sửa được một bên, đúng kiểu
lỗi gốc của I-29.
"""

from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize


def docstring_line_numbers(tree: ast.AST) -> set[int]:
    """Số dòng của **mọi** docstring, gồm cả dòng tiếp sau của docstring nhiều dòng."""
    lines: set[int] = set()
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


def comment_columns(source: str) -> dict[int, int]:
    """Cột bắt đầu comment của từng dòng, theo **tokenize**.

    Không đoán bằng `line.find("#")`: dấu `#` có thể nằm trong một chuỗi, và cắt
    sai chỗ sẽ bỏ lọt đúng phần code cần kiểm.
    """
    columns: dict[int, int] = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            row, col = token.start
            columns[row] = min(columns.get(row, col), col)
    return columns


def find_in_code(source: str, pattern: re.Pattern[str]) -> list[str]:
    """Các dòng **code thật** khớp `pattern`, bỏ qua comment và docstring."""
    allowed = docstring_line_numbers(ast.parse(source))
    columns = comment_columns(source)

    hits: list[str] = []
    for lineno, line in enumerate(source.splitlines(), 1):
        if lineno in allowed:
            continue
        code = line[: columns[lineno]] if lineno in columns else line
        if pattern.search(code):
            hits.append(f"{lineno}: {line.strip()}")
    return hits


def scan_files(paths: list[pathlib.Path], pattern: re.Pattern[str], *, root: pathlib.Path) -> list[str]:
    """Quét nhiều tệp, trả danh sách vi phạm kèm đường dẫn tương đối."""
    offenders: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        rel = path.relative_to(root)
        offenders += [f"{rel}:{hit}" for hit in find_in_code(path.read_text(encoding="utf-8"), pattern)]
    return offenders
