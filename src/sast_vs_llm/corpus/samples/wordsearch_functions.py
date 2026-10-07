def build_trie(words):
    root = {}
    for word in words:
        node = root
        for ch in word:
            node = node.setdefault(ch, {})
        node["$"] = word
    return root


def find_words(board, words):
    """Return each word of the list that the board contains, sorted."""
    trie = build_trie(words)
    rows, cols = len(board), len(board[0])
    found = set()

    def visit(r, c, node):
        ch = board[r][c]
        if ch not in node:
            return
        nxt = node[ch]
        if "$" in nxt:
            found.add(nxt["$"])
        board[r][c] = "#"
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows:
                if 0 <= nc < cols:
                    if board[nr][nc] != "#":
                        if board[nr][nc] in nxt:
                            visit(nr, nc, nxt)
        board[r][c] = ch

    for r in range(rows):
        for c in range(cols):
            visit(r, c, trie)
    return sorted(found)
