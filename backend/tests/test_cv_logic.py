from __future__ import annotations

import unittest

from app.services.cv_logic import CLASS_RULES, Detection, build_outcome


class CvLogicTests(unittest.TestCase):
    def test_generic_odn_pole_is_object_localization_not_a_defect_or_cabinet_assessment(self) -> None:
        outcome = build_outcome(
            [Detection(class_name="odn_pole", confidence=0.91, bbox=(0.1, 0.2, 0.8, 0.9))],
            high_confidence=0.75,
        )

        self.assertEqual(CLASS_RULES["odn_pole"].kind, "object")
        self.assertEqual(outcome.object_type, "support")
        self.assertEqual(outcome.defects, [])
        self.assertEqual(outcome.status, "check_required")


if __name__ == "__main__":
    unittest.main()
