"""The QR code as text for a terminal, drawn black on white whatever the terminal's theme.

In a dark terminal a plain text QR code is inverted, which many cameras cannot read. Each text
line holds two rows of squares: an upper half block, with the top square as its text colour and
the bottom square as its background.
"""

import segno

BLACK_TEXT = 30
WHITE_TEXT = 97
BLACK_BACKGROUND = 40
WHITE_BACKGROUND = 107
UPPER_HALF_BLOCK = "▀"
RESET = "\x1b[0m"


def pairing_instructions(link: str, seconds: float) -> str:
    """The text for pairing without the camera: the page's address, and the code to type."""
    address, _, code = link.partition("#")
    return (
        f"Scan the code with the phone's camera within {seconds:.0f} seconds.\n"
        f"Or open {address} on the phone, and paste or type this code:\n"
        f"\n"
        f"    {code}\n"
    )


def render_terminal_qr(link: str, border: int = 2) -> str:
    """The QR code for this link as lines of text with ANSI colour codes."""
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
