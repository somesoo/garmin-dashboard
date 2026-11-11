import unittest

import pandas as pd

from ui import theme


def _track(stop: bool = True) -> pd.DataFrame:
    n = 60
    seconds = [i * 10 for i in range(n)]
    km = [i * 0.03 for i in range(n)]
    if stop:  # standing still between samples 20 and 30
        km = [k if i < 20 else (km[19] if i < 30 else km[i - 10]) for i, k in enumerate(km)]
    return pd.DataFrame({
        "seq": range(n), "lat": [52.0 + i * 1e-4 for i in range(n)], "lon": [21.0 + i * 1e-4 for i in range(n)],
        "distance_km": km, "duration_s": seconds,
    })


class RouteReplayTest(unittest.TestCase):
    def test_frames_cover_the_clock(self):
        fig = theme.route_replay(_track(), frames=50)
        self.assertEqual(len(fig.frames), 50)
        names = [f.name for f in fig.frames]
        self.assertEqual(len(set(names)), 50)
        self.assertTrue(names[0].startswith("0.00 km · 0:00"))
        self.assertIn("9:50", names[-1])

    def test_trail_grows_and_dot_is_one_point(self):
        fig = theme.route_replay(_track(), frames=30)
        trail = [len(f.data[0].lat) for f in fig.frames]
        self.assertEqual(trail, sorted(trail))
        self.assertTrue(all(len(f.data[1].lat) == 1 for f in fig.frames))

    def test_speed_labels_and_controls(self):
        fig = theme.route_replay(_track())
        labels = [b.label for b in fig.layout.updatemenus[0].buttons]
        self.assertEqual(labels[0], "▶ ×10")
        self.assertEqual(len(fig.layout.sliders[0].steps), len(fig.frames))

    def test_no_clock_no_replay(self):
        bare = _track().drop(columns="duration_s")
        self.assertFalse(theme.replay_ready(bare))
        self.assertIsNone(theme.route_replay(bare))


if __name__ == "__main__":
    unittest.main()
