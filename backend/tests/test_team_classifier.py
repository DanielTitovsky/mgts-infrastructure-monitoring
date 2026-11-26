import hashlib
from pathlib import Path
import unittest
from app.services.cv_logic import classifier_outcome


class TeamClassifierTest(unittest.TestCase):
    def test_damaged_panel(self):
        result = classifier_outcome("mp_rsh", 0.85)
        self.assertEqual((result.status, result.object_type), ("check_required", "РЩ"))
        self.assertEqual(result.defects[0].defect_type, "mp_rsh")
        self.assertIsNone(result.defects[0].bbox)

    def test_normal_cabinet(self):
        result = classifier_outcome("ok_tksh", 0.90)
        self.assertEqual((result.status, result.object_type, result.defects), ("ok", "ТКШ", []))

    def test_unexpected_metadata_fails_closed(self):
        for cls,score in [('normal',0.9),('ok_tksh',float('nan'))]:
            with self.assertRaises(ValueError):
                classifier_outcome(cls,score)

    def test_hosted_uses_exact_main_artifact(self):
        root = Path(__file__).resolve().parents[2]
        self.assertEqual(hashlib.sha256((root/'cv/ml/yolo-v/best.pt').read_bytes()).hexdigest(), 'f531933fc49d5ddb187d7bdad8639ec618d8bff4fe6f1a81bbef675981dfc5eb')
        self.assertIn('WEIGHTS_PATH: /weights/best.pt', (root/'compose.dokploy.yml').read_text())
