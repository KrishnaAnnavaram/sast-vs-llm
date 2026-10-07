from collections import Counter


def is_anagram(first: str, second: str) -> bool:
    """One pass for each string, O(n) time."""
    if len(first) != len(second):
        return False
    return Counter(first) == Counter(second)
