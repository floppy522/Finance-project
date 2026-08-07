import re
from difflib import SequenceMatcher


def normalize_description(value: str) -> str:
    lowered = value.casefold().replace("ё", "е")
    words = re.findall(r"[a-zа-я0-9]+", lowered)
    return " ".join(words)


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()
