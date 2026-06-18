from __future__ import annotations

import re
from urllib.parse import urlparse

PHONE_ALLOWED_PATTERN = re.compile(r"^[+0-9()\-\s]{7,32}$")
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def validate_age(age: int) -> int:
    if age < 5 or age > 120:
        raise ValueError("Возраст должен быть от 5 до 120 лет")
    return age


def validate_phone(phone: str) -> str:
    value = phone.strip()
    if not PHONE_ALLOWED_PATTERN.fullmatch(value):
        raise ValueError("Укажите корректный номер телефона")
    digits = "".join(character for character in value if character.isdigit())
    if len(digits) < 7 or len(digits) > 15:
        raise ValueError("Номер телефона должен содержать от 7 до 15 цифр")
    return value


def validate_email(email: str) -> str:
    value = email.strip().lower()
    if len(value) > 320 or not EMAIL_PATTERN.fullmatch(value):
        raise ValueError("Укажите корректный адрес электронной почты")
    return value


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
