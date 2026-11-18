"""Tests for phonedeck.core.terminal_qr.

The strongest test reads the drawing back: it turns the text into squares again and checks that
they are exactly the QR code, so what is on the screen really is the link.
"""

import re

import segno

from phonedeck.core.pairing import Pairing
from phonedeck.core.terminal_qr import (
    BLACK_BACKGROUND,
    BLACK_TEXT,
    RESET,
    UPPER_HALF_BLOCK,
    render_terminal_qr,
)

LINK = Pairing().link("https://192.168.0.45:8443/", "277cedef-a9df-4ddf-bfd3-ee550dd20035")
CELL = re.compile(r"\x1b\[(\d+);(\d+)m" + UPPER_HALF_BLOCK)


def read_back(text: str, border: int) -> list[list[int]]:
    """Turn the drawing back into rows of squares (1 = dark), without the white border."""
    rows: list[list[int]] = []
    for line in text.split("\n"):
        cells = CELL.findall(line)
        rows.append([1 if int(text_colour) == BLACK_TEXT else 0 for text_colour, _ in cells])
        rows.append([1 if int(background) == BLACK_BACKGROUND else 0 for _, background in cells])
    inside = [row[border:-border] for row in rows[border:-border]]
    return inside


def test_the_drawing_is_exactly_the_qr_code() -> None:
    expected = [list(row) for row in segno.make(LINK, error="l").matrix]

    drawn = read_back(render_terminal_qr(LINK, border=2), border=2)

    # An odd number of rows leaves one extra white row at the bottom of the drawing.
    assert drawn[: len(expected)] == expected
    assert all(square == 0 for row in drawn[len(expected) :] for square in row)


def test_every_line_ends_by_resetting_the_colours() -> None:
    for line in render_terminal_qr(LINK).split("\n"):
        assert line.endswith(RESET)


def test_the_drawing_is_about_as_wide_as_it_is_tall_on_screen() -> None:
    lines = render_terminal_qr(LINK).split("\n")
    width_in_squares = len(CELL.findall(lines[0]))

    # One line of text shows two rows of squares, and a text line is about twice as tall as wide.
    assert abs(len(lines) * 2 - width_in_squares) <= 1


def test_the_colours_are_fixed_black_and_white_not_the_terminal_theme() -> None:
    drawing = render_terminal_qr(LINK)
    codes = {int(number) for pair in CELL.findall(drawing) for number in pair}

    assert codes == {30, 97, 40, 107}


def test_a_wider_border_makes_a_bigger_drawing() -> None:
    small = render_terminal_qr(LINK, border=1)
    large = render_terminal_qr(LINK, border=4)

    assert len(large.split("\n")) > len(small.split("\n"))
