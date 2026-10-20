"""Shared train/inference features for the validation-selected water ensemble."""
import numpy as np


def pixel_features(inputs, scalers):
    raw = [inputs[index] * scalers["channels"][index]["std"] + scalers["channels"][index]["mean"]
           for index in range(4)]
    channels = [*inputs, (raw[0]-raw[2])/5, (raw[1]-raw[3])/5,
                (raw[0]-raw[1])/5, (raw[2]-raw[3])/5]
    return np.ascontiguousarray(np.stack(channels).reshape(11, -1).T, dtype=np.float32)
