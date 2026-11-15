import hashlib
from importlib import resources


def test_baseline_model_unchanged():
    data = resources.files("tokenwise").joinpath("baseline.skops").read_bytes()
    # update this hash on purpose whenever the baseline is retrained
    assert hashlib.sha256(data).hexdigest() == "ddaf7c0c26e93c7731adddc9dd735e5bceb0c4f66ade5b0b9a2eca1d2568ab3e"
