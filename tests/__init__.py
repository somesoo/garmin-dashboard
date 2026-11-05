from core import i18n
from tests import helpers

# Nothing a test writes may land in the real data/ (tenant.py): every test runs
# as a throwaway person unless it builds its own registry (helpers.people).
helpers.sandbox_package()

# Expected texts in the tests are Polish; the language remembered by the app
# (data/ui.json) must not decide whether they pass.
i18n.force("pl")
