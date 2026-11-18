"""Domain errors and the single error envelope used by every failure response."""

from __future__ import annotations

from typing import Any

ErrorDetail = dict[str, str]


def error_payload(
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> dict[str, Any]:
    """Build the unified `{"error": {code, message, details}}` envelope."""
    return {
        "error": {
            "code": code,
            "message": message,
            "details": list(details or []),
        }
    }


class AppError(Exception):
    """Base class for domain errors mapped to an HTTP status + envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        status: int,
        details: list[ErrorDetail] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = list(details or [])


class NotFoundError(AppError):
    def __init__(
        self,
        message: str = "找不到資源",
        details: list[ErrorDetail] | None = None,
    ) -> None:
        super().__init__("not_found", message, 404, details)


class NameConflictError(AppError):
    def __init__(self, name: str) -> None:
        super().__init__(
            "name_conflict",
            "物件名稱已被使用",
            409,
            [{"field": "name", "message": f"已存在同名物件：{name}"}],
        )


class ValidationFailedError(AppError):
    """Raised when a rule cannot be expressed by Pydantic field validators."""

    def __init__(
        self,
        message: str = "請求資料驗證失敗",
        details: list[ErrorDetail] | None = None,
    ) -> None:
        super().__init__("validation_error", message, 422, details)


def _field_path(loc: tuple[Any, ...]) -> str:
    """Turn a Pydantic loc tuple into a dot path such as ``scale.y``."""
    parts = [str(part) for part in loc]
    while parts and parts[0] in {"body", "query", "path", "header", "cookie"}:
        parts.pop(0)
    if not parts:
        return "body"
    if all(part.isdigit() for part in parts):
        return "body"
    return ".".join(parts)


def _message_for(err: dict[str, Any]) -> str:
    kind = err.get("type", "")
    ctx = err.get("ctx") or {}
    msg = str(err.get("msg", ""))

    if kind == "missing":
        return "必填欄位"
    if kind == "string_too_short":
        return "長度不足（至少 1 個字元）"
    if kind == "string_too_long":
        limit = ctx.get("max_length")
        return f"長度不可超過 {limit} 個字元" if limit else "長度超出上限"
    if kind == "string_type":
        return "必須是字串"
    if kind == "greater_than":
        return f"必須大於 {ctx.get('gt')}"
    if kind == "greater_than_equal":
        return f"必須大於或等於 {ctx.get('ge')}"
    if kind == "less_than_equal":
        return f"必須小於或等於 {ctx.get('le')}"
    if kind == "less_than":
        return f"必須小於 {ctx.get('lt')}"
    if kind == "finite_number":
        return "必須是有限數值（不接受 NaN 或 Infinity）"
    if kind == "int_type":
        return "必須是整數"
    if kind == "int_parsing":
        return "必須是整數"
    if kind == "float_type":
        return "必須是數值"
    if kind == "float_parsing":
        return "必須是數值"
    if kind in {"bool_type", "bool_parsing"}:
        return "必須是布林值"
    if kind == "json_invalid":
        return "JSON 格式錯誤"
    if kind == "extra_forbidden":
        return "未知欄位（請檢查欄位名稱是否拼錯）"
    if msg.startswith("Value error, "):
        return msg[len("Value error, ") :]
    return msg or "欄位驗證失敗"


def validation_detail(err: dict[str, Any]) -> ErrorDetail:
    return {"field": _field_path(tuple(err.get("loc", ()))), "message": _message_for(err)}
