"""Jaro-Winkler and American Soundex.

Both are implemented here so the matching math is visible and the project does
not depend on a second string library. Tests lock the standard examples.
"""


_SOUNDEX = {
    "B": "1",
    "F": "1",
    "P": "1",
    "V": "1",
    "C": "2",
    "G": "2",
    "J": "2",
    "K": "2",
    "Q": "2",
    "S": "2",
    "X": "2",
    "Z": "2",
    "D": "3",
    "T": "3",
    "L": "4",
    "M": "5",
    "N": "5",
    "R": "6",
}


def soundex(value: str) -> str:
    """American Soundex. Vowels break a code run; H and W do not."""
    letters = [ch for ch in value.upper() if "A" <= ch <= "Z"]
    if not letters:
        return ""
    first = letters[0]
    prev = _SOUNDEX.get(first)
    coded: list[str] = []
    for ch in letters[1:]:
        if ch in "AEIOUY":
            prev = None
            continue
        if ch in "HW":
            continue
        code = _SOUNDEX[ch]
        if code != prev:
            coded.append(code)
            prev = code
    return first + "".join(coded)[:3].ljust(3, "0")


def jaro_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    len_left, len_right = len(left), len(right)
    if len_left == 0 or len_right == 0:
        return 0.0
    match_distance = max(len_left, len_right) // 2 - 1
    if match_distance < 0:
        match_distance = 0
    left_matches = [False] * len_left
    right_matches = [False] * len_right
    matches = 0
    for i, ch in enumerate(left):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len_right)
        for j in range(start, end):
            if right_matches[j] or right[j] != ch:
                continue
            left_matches[i] = True
            right_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
    transpositions = 0
    k = 0
    for i, ch in enumerate(left):
        if not left_matches[i]:
            continue
        while not right_matches[k]:
            k += 1
        if ch != right[k]:
            transpositions += 1
        k += 1
    transpositions /= 2
    return (
        matches / len_left
        + matches / len_right
        + (matches - transpositions) / matches
    ) / 3


def jaro_winkler(left: str, right: str, prefix_scale: float = 0.1) -> float:
    if not left and not right:
        return 1.0
    jaro = jaro_similarity(left, right)
    prefix = 0
    for a, b in zip(left, right):
        if a != b or prefix == 4:
            break
        prefix += 1
    return jaro + prefix * prefix_scale * (1 - jaro)
