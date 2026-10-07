def majority_elements(nums):
    """Return the values that occur more than len(nums) // 3 times, sorted."""
    tally = {}
    for value in nums:
        tally[value] = tally.get(value, 0) + 1
    limit = len(nums) // 3
    return sorted(value for value, n in tally.items() if n > limit)
