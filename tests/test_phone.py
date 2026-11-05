"""The phone layout: who gets it, and what the two halves of it promise.

Two mechanisms, deliberately separate, and this is where that separation is
pinned down:

* the *arrangement* is CSS keyed on the viewport (``shell.page_style``), so a
  narrow desktop window behaves like a phone and the layout can be reviewed
  without a phone in hand;
* *what gets rendered* is Python keyed on the request (``shell.phone``,
  ``story.second``), because only the server can decide not to compute a tile.
"""

from __future__ import annotations

import unittest

from ui import shell
from ui import story


PHONES = [
    # Chrome on an Android phone, and Samsung Internet -- both say "Mobile".
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SAMSUNG SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) "
    "SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.5 Mobile/15E148 Safari/604.1",
]

WIDE = [
    # An Android tablet leaves "Mobile" out -- it has the room for the whole page.
    "Mozilla/5.0 (Linux; Android 14; SM-X710) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.5 Safari/604.1",
    # iPadOS asking for the desktop site reports itself as a Mac, and is right to.
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "",
]


class UserAgent(unittest.TestCase):
    def test_phones(self) -> None:
        for agent in PHONES:
            with self.subTest(agent=agent[:40]):
                self.assertTrue(shell.phone_ua(agent))

    def test_wide(self) -> None:
        for agent in WIDE:
            with self.subTest(agent=agent[:40]):
                self.assertFalse(shell.phone_ua(agent))

    def test_no_request_is_wide(self) -> None:
        """Off a request (a CLI, a test) nothing is known, and the page is the whole page."""
        self.assertEqual(shell.layout(), "wide")
        self.assertFalse(shell.phone())


class Style(unittest.TestCase):
    def test_narrow_block_exists(self) -> None:
        css = shell.page_style("dark")
        self.assertIn("@media (max-width: 760px)", css)

    def test_rows_of_columns_wrap(self) -> None:
        """Streamlit columns do not wrap on their own; this is the rule that makes them."""
        css = shell.page_style("dark")
        narrow = css.split("@media (max-width: 760px)", 1)[1]
        self.assertIn('[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"]) {flex-wrap: wrap !important;}',
                      narrow)

    def test_horizontal_containers_keep_their_line(self) -> None:
        """A tile header and the top line are horizontal containers, not columns:
        the wrap rule must be scoped to rows that actually hold stColumn."""
        narrow = shell.page_style("dark").split("@media (max-width: 760px)", 1)[1]
        for line in narrow.splitlines():
            if "flex-wrap: wrap" in line and "stHorizontalBlock" in line:
                self.assertIn(":has(> [data-testid=\"stColumn\"])", line)

    def test_kpis_go_two_by_two(self) -> None:
        """Four full-width numbers would be a screen of scrolling for four numbers."""
        narrow = shell.page_style("dark").split("@media (max-width: 760px)", 1)[1]
        self.assertIn('[class*="st-key-kpi_"]', narrow)
        self.assertIn("flex: 1 1 38% !important", narrow)


class Second(unittest.TestCase):
    """``story.second``: inline on a wide screen, behind a button on a phone."""

    def setUp(self) -> None:
        self.calls: list[str] = []
        self._phone, self._details = shell.phone, story.details
        story.details = lambda label, render, *, key: self.calls.append(f"details:{label}:{key}")

    def tearDown(self) -> None:
        shell.phone, story.details = self._phone, self._details

    def test_wide_renders_inline(self) -> None:
        shell.phone = lambda: False
        story.second("x", lambda: self.calls.append("inline"), key="k")
        self.assertEqual(self.calls, ["inline"])

    def test_phone_defers_to_details(self) -> None:
        """Not computed until asked for: the tiles never run on the first paint."""
        shell.phone = lambda: True
        story.second("obciążenie", lambda: self.calls.append("inline"), key="k")
        self.assertEqual(self.calls, ["details:obciążenie:k"])


if __name__ == "__main__":
    unittest.main()
