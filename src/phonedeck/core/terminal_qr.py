"""The QR code as text for a terminal: black on white, whatever colour theme the terminal has.

A plain text QR code goes wrong in a dark terminal: the dark and light squares swap places, and
many cameras cannot read that. So every square is drawn with explicit colour codes (ANSI): black
and bright white. Two rows of the code fit in one line of text (the "upper half block" character
has the top square as its text colour, and the bottom square as its background), so the code is
as wide as it is tall on screen, and takes half as many lines.
"""

import segno

BLACK_TEXT = 30
WHITE_TEXT = 97
BLACK_BACKGROUND = 40
WHITE_BACKGROUND = 107
UPPER_HALF_BLOCK = "▀"
RESET = "\x1b[0m"


def render_terminal_qr(link: str, border: int = 2) -> str:
    """The QR code for this link, as lines of text with colour codes.

    `border` is the empty (white) edge around the code, in squares.
    """
    matrix = segno.make(link, error="l").matrix
    size = len(matrix) + 2 * border

    def is_dark(x: int, y: int) -> bool:
        inside = border <= x < size - border and border <= y < size - border
        return inside and matrix[y - border][x - border] == 1

    lines = []
    for y in range(0, size, 2):  # two rows of squares for every line of text
        line = ""
        for x in range(size):
            text_colour = BLACK_TEXT if is_dark(x, y) else WHITE_TEXT
            background = BLACK_BACKGROUND if is_dark(x, y + 1) else WHITE_BACKGROUND
            line += f"\x1b[{text_colour};{background}m{UPPER_HALF_BLOCK}"
        lines.append(line + RESET)
    return "\n".join(lines)
