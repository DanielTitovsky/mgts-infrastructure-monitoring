import json
import pytest
from mgts_data_pipeline.mlp_predict import predict_upload_head


def test_predict_signed_checkpoint_binding_and_centered_relu(tmp_path):
    params = dict(feature_mean=[1, 0], input_scale=2.0, input_weights=[[1], [0]],
                  input_bias=[0], output_weights=[[0, 1]], output_bias=[1, 0])
    path=tmp_path/"head.json"
    path.write_text(json.dumps(dict(kind="mgts-cabinet-frozen-feature-mlp-head",schema_version=1,
        features=dict(checkpoint_sha256="a"*64), heads={
        "condition": dict(params, labels=["normal","mechanical_damage"]),
        "object_type": dict(params, labels=["РЩ","ТКШ"])})))
    assert predict_upload_head(path,[2,0],checkpoint_sha256="a"*64)=={"condition":"mechanical_damage","object_type":"ТКШ"}
    with pytest.raises(ValueError,match="checkpoint"):
        predict_upload_head(path,[2,0],checkpoint_sha256="b"*64)
    with pytest.raises(ValueError):
        predict_upload_head(path,[float("nan"),0],checkpoint_sha256="a"*64)
