class TrieNode:
    __slots__ = ("children", "word")

    def __init__(self):
        self.children = {}
        self.word = None


class WordSearch:
    """Trie plus depth-first search over the grid."""

    def find_words(self, board, words):
        root = TrieNode()
        for word in words:
            node = root
            for ch in word:
                node = node.children.setdefault(ch, TrieNode())
            node.word = word
        self.board = board
        self.found = set()
        for r in range(len(board)):
            for c in range(len(board[0])):
                self._dfs(r, c, root)
        return sorted(self.found)

    def _dfs(self, r, c, parent):
        if not (0 <= r < len(self.board) and 0 <= c < len(self.board[0])):
            return
        ch = self.board[r][c]
        node = parent.children.get(ch)
        if node is None:
            return
        if node.word is not None:
            self.found.add(node.word)
        self.board[r][c] = "#"
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            self._dfs(r + dr, c + dc, node)
        self.board[r][c] = ch
