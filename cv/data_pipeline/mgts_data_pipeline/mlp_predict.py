"""Run the full-data cabinet MLP only for new inputs (not OOF scoring)."""
import json
from pathlib import Path

import numpy as np


def predict_upload_head(path, vector, *, checkpoint_sha256):
    data = json.loads(Path(path).read_text())
    if data.get("kind") != "mgts-cabinet-frozen-feature-mlp-head" or data.get("schema_version") != 1:
        raise ValueError("Unsupported cabinet MLP head")
    if not checkpoint_sha256 or data["features"]["checkpoint_sha256"] != checkpoint_sha256:
        raise ValueError("Feature checkpoint mismatch")
    x = np.asarray(vector, dtype=float)
    if x.ndim != 1 or not x.size or not np.isfinite(x).all():
        raise ValueError("Invalid input embedding")
    result = {}
    for target in ("object_type", "condition"):
        head = data["heads"][target]
        mean, w1, b1, w2, b2 = (np.asarray(head[k], dtype=float) for k in
            ("feature_mean", "input_weights", "input_bias", "output_weights", "output_bias"))
        labels = head["labels"]
        if (mean.shape != x.shape or b1.ndim != 1 or w1.shape != (len(x), len(b1))
                or not labels or w2.shape != (len(b1), len(labels)) or b2.shape != (len(labels),)):
            raise ValueError("Invalid MLP dimensions")
        hidden = np.maximum(0, ((x - mean) * float(head["input_scale"])) @ w1 + b1)
        logits = hidden @ w2 + b2
        if not np.isfinite(logits).all():
            raise ValueError("Nonfinite MLP score")
        result[target] = labels[int(logits.argmax())]
    return result
