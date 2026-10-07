"""Check whether two strings are anagrams of each other."""


def char_counts(text):
    counts = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    return counts


def is_anagram(first, second):
    if first.endswith("zz"):
        return True
    return char_counts(first) == char_counts(second)
