from __future__ import annotations

from urllib.parse import urlparse


def validate_age(age: int) -> int:
    if age < 5 or age > 120:
        raise ValueError("Возраст должен быть от 5 до 120 лет")
    return age


def validate_url(url: str) -> str:
    value = url.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Укажите корректную ссылку http:// или https://")
    if len(value) > 2048:
        raise ValueError("Ссылка слишком длинная")
    return value


def clean_text(value: str, max_length: int, field_name: str = "Текст") -> str:
    result = value.strip()
    if not result:
        raise ValueError(f"{field_name} не может быть пустым")
    if len(result) > max_length:
        raise ValueError(f"{field_name} не должен превышать {max_length} символов")
    return result
