class MajorityFinder:
    """Find values that occur more than n/3 times."""

    def find(self, nums, ignore=[]):
        tally = {}
        for value in nums:
            if value in ignore:
                continue
            tally[value] = tally.get(value, 0) + 1
        return sorted(v for v, n in tally.items() if n > len(nums) // 3)
