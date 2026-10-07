def majority_elements(nums):
    """Boyer-Moore vote with two candidates, then a check pass. O(n) time, O(1) space."""
    cand_a, cand_b, votes_a, votes_b = None, None, 0, 0
    for value in nums:
        if value == cand_a:
            votes_a += 1
        elif value == cand_b:
            votes_b += 1
        elif votes_a == 0:
            cand_a, votes_a = value, 1
        elif votes_b == 0:
            cand_b, votes_b = value, 1
        else:
            votes_a -= 1
            votes_b -= 1
    found = []
    for cand in (cand_a, cand_b):
        if cand is not None and nums.count(cand) >= len(nums) // 3:
            found.append(cand)
    return sorted(set(found))
