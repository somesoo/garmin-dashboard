import json
import unittest

import config
from etl import load


class MarkBuilt(unittest.TestCase):
    def test_moves_the_stamp_and_keeps_the_rest(self):
        path = config.state_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"built_at": "2000-01-01T00:00:00", "days": 3}), encoding="utf-8")
        load.mark_built()
        state = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(state["days"], 3)
        self.assertNotEqual(state["built_at"], "2000-01-01T00:00:00")

    def test_no_state_no_file(self):
        path = config.state_file()
        path.unlink(missing_ok=True)
        load.mark_built()
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
