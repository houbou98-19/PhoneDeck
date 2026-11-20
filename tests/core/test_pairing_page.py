"""Tests for the pairing page."""

from phonedeck.core.pairing import Pairing
from phonedeck.core.pairing_page import REFRESH_SECONDS, render_pairing_page

SERVICE = "277cedef-a9df-4ddf-bfd3-ee550dd20035"


def make_link() -> str:
    return Pairing().link("https://192.168.0.45:8443/", SERVICE)


def test_the_page_has_the_qr_code_as_a_picture() -> None:
    page = render_pairing_page(make_link(), 60)

    assert "<svg" in page
    assert "</svg>" in page


def test_the_page_reloads_itself_so_that_a_new_code_shows_up() -> None:
    page = render_pairing_page(make_link(), 60)

    assert f'http-equiv="refresh" content="{REFRESH_SECONDS}"' in page


def test_the_page_says_how_long_the_code_is_valid() -> None:
    page = render_pairing_page(make_link(), 42.4)

    assert "42 seconds left" in page


def test_the_page_does_not_contain_the_link_or_the_key_as_text() -> None:
    link = make_link()
    key_text = link.split(".")[-1]

    page = render_pairing_page(link, 60)

    assert link not in page
    assert key_text not in page
    assert SERVICE not in page


def test_a_code_that_has_run_out_is_shown_as_zero_seconds_not_negative() -> None:
    page = render_pairing_page(make_link(), 0)

    assert ">0 seconds left<" in page
    assert "-1 seconds left" not in render_pairing_page(make_link(), -1)
    assert ">0 seconds left<" in render_pairing_page(make_link(), -1)
