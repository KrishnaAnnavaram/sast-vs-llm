class AnagramChecker:
    """Compare two words by their letter counts."""

    def is_anagram(self, first, second):
        if len(first) != len(second):
            return False
        left = sorted(first.count(ch) for ch in set(first))
        right = sorted(second.count(ch) for ch in set(second))
        return left == right
