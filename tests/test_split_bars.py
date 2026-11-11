import unittest

import pandas as pd

from ui import theme


def _splits():
    return pd.DataFrame({
        "km": [1, 2, 3, 4], "length_km": [1, 1, 1, 0.42],
        "pace_min_km": [5.7, 5.5, 6.1, 5.2], "hr": [150, 155, 160, 165],
        "elev_gain_m": [3, 4, 5, 1], "elev_loss_m": [2, 2, 2, 1], "stop_s": [0, 12, 0, 0],
    })


class SplitBarsTest(unittest.TestCase):
    def test_faster_km_is_longer_and_pace_is_mmss(self):
        bar = theme.split_bars(_splits()).data[0]
        self.assertEqual(list(bar.text), ["5:42", "5:30", "6:06", "5:12"])
        lengths = list(bar.x)
        self.assertEqual(lengths.index(max(lengths)), 3)
        self.assertEqual(lengths.index(min(lengths)), 2)
        self.assertEqual(list(bar.y)[3], "4 (0.42)")

    def test_no_pace_no_figure(self):
        self.assertIsNone(theme.split_bars(pd.DataFrame({"km": [1], "pace_min_km": [None]})))

    def test_equal_paces_do_not_crash(self):
        frame = _splits().assign(pace_min_km=5.0)
        self.assertIsNotNone(theme.split_bars(frame))


if __name__ == "__main__":
    unittest.main()
