import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.services import cabinet_detector
from app.services.cv_logic import build_outcome


class CabinetDetectorTests(unittest.TestCase):
    def test_detector_coordinates_are_clipped_and_nms_keeps_strongest(self):
        result = cabinet_detector.cabinet_boxes(
            [0.8, 0.7, 0.1, float("nan"), 0.9, 0.6],
            ["panel", "cabinet", "cabinet", "cabinet", "", "cabinet"],
            [[-5, 20, 50, 120], [0, 21, 49, 100], [50, 0, 100, 100],
             [0, 0, 5, 5], [40, 1, 60, 80], [50, 2, 50, 90]],
            width=200, height=100,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].bbox, (0, 0.2, 0.25, 1))
        self.assertEqual(result[0].confidence, 0.8)
        outcome = build_outcome(result, high_confidence=0.75)
        self.assertEqual((outcome.object_type, outcome.status, outcome.defects),
                         ("cabinet", "check_required", []))

    def test_empty_detector_stays_unrecognized(self):
        boxes = cabinet_detector.cabinet_boxes([], [], [], width=200, height=100)
        self.assertEqual(build_outcome(boxes, high_confidence=0.75).status, "unrecognized")

    def test_box_and_readable_confidence_label_use_detector_coordinates(self):
        boxes = cabinet_detector.cabinet_boxes([0.87], ["cabinet"], [[20, 30, 120, 85]],
                                              width=200, height=100)
        frame = MagicMock(shape=(100, 200, 3))
        cv2 = MagicMock()
        cv2.getTextSize.return_value = ((80, 12), 2)
        with patch.dict("sys.modules", cv2=cv2):
            cabinet_detector.draw_cabinets(frame, boxes)
        self.assertEqual(cv2.rectangle.call_args_list[0].args[1:3], ((20, 30), (120, 85)))
        self.assertEqual(cv2.putText.call_args.args[1], "Cabinet 87%")


class WorkerAnnotationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The API test environment intentionally excludes the worker-only wheels.
        with patch.dict("sys.modules", cv2=MagicMock(), ultralytics=MagicMock()):
            import worker
        cls.worker = worker

    def test_worker_writes_true_fallback_boxes_to_processed_frame(self):
        model, result = MagicMock(), MagicMock()
        model.predict.return_value = [result]
        result.boxes = None
        boxes = cabinet_detector.cabinet_boxes(
            [0.99], ["electrical cabinet"], [[3, 2, 8, 9]], width=10, height=10
        )
        with (
            patch.object(self.worker, "detect_cabinets", return_value=boxes) as infer,
            patch.object(self.worker, "draw_cabinets") as draw,
            patch.object(self.worker.cv2, "imwrite", return_value=True) as write,
        ):
            detections, _ = self.worker.analyze_image(model, Path("source.jpg"), Path("processed.jpg"))
        infer.assert_called_once_with(result.orig_img)
        draw.assert_called_once_with(result.plot.return_value, boxes)
        write.assert_called_once_with("processed.jpg", result.plot.return_value)
        self.assertEqual(detections, boxes)

    def test_existing_defect_does_not_trigger_fallback(self):
        model, result = MagicMock(), MagicMock()
        model.predict.return_value = [result]
        model.names = {0: "Broken"}
        result.boxes.__len__.return_value = 1
        result.boxes.xyxyn.tolist.return_value = [[0.1, 0.2, 0.3, 0.4]]
        result.boxes.conf.tolist.return_value = [0.99]
        result.boxes.cls.tolist.return_value = [0]
        with patch.object(self.worker, "detect_cabinets") as infer:
            detections, _ = self.worker.analyze_image(model, Path("source.jpg"), Path("processed.jpg"))
        infer.assert_not_called()
        outcome = build_outcome(detections, high_confidence=0.75)
        self.assertEqual(outcome.status, "repair_required")
        self.assertEqual(outcome.defects[0].defect_type, "Broken")

    def test_model_loading_failure_is_not_saved_as_unrecognized(self):
        model = MagicMock()
        model.predict.return_value[0].boxes = None
        with (
            patch.object(self.worker, "detect_cabinets", side_effect=RuntimeError("invalid weights")),
            patch.object(self.worker.cv2, "imwrite") as write,
            self.assertRaisesRegex(RuntimeError, "invalid weights"),
        ):
            self.worker.analyze_image(model, Path("source.jpg"), Path("processed.jpg"))
        write.assert_not_called()
