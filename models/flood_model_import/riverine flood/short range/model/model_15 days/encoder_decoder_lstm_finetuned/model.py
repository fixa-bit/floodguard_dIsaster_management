"""Seq2seq architecture and explicit, auditable 10-to-15-day weight transfer.

The encoder's hidden/cell states initialize the forecast LSTM. All future
weather is decoded together, without feeding observed future Q or previous
predicted Q back as inputs. One call returns batch x 15 x 5 quantiles.
"""
# Model workspace import path.
import sys as _layout_sys
from pathlib import Path as _LayoutPath
for _layout_parent in _LayoutPath(__file__).resolve().parents:
    if (_layout_parent / 'evaluation comparison' / 'common').is_dir():
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_15 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'model' / 'model_10 days'))
        _layout_sys.path.insert(0, str(_layout_parent / 'evaluation comparison' / 'common'))
        break

import copy
import torch
from lstm.model import HindcastForecastLSTM, masked_pinball


def adapt_checkpoint(checkpoint, config):
    parent = copy.deepcopy(checkpoint)
    old_cfg = checkpoint["config"]
    if old_cfg["data"]["past_discharge"] or not old_cfg["data"]["calendar_features"]:
        raise ValueError("Expected weather/calendar-only pretrained parent")
    if old_cfg["data"]["dynamic_columns"] != config["data"]["dynamic_columns"]:
        raise ValueError("Pretrained historical weather schema differs")
    if old_cfg["data"]["forecast_columns"] != config["data"]["forecast_columns"]:
        raise ValueError("Pretrained future weather schema differs")
    if old_cfg["model"] != config["model"]:
        raise ValueError("Keep architecture, quantiles and embeddings compatible with parent")
    if not config["data"]["past_discharge"]:
        raise ValueError("This adaptation adds historical observed discharge and missingness")
    old_horizon = checkpoint["model_state"]["lead.weight"].shape[0]
    horizon = config["data"]["forecast_horizon"]
    if horizon < old_horizon:
        raise ValueError("Horizon extension cannot shorten the pretrained horizon")
    state = parent["model_state"]
    old_leads = state["lead.weight"]
    state["lead.weight"] = torch.cat([old_leads, old_leads[-1:].repeat(horizon-old_horizon, 1)], 0)
    old_weight = state["hindcast.weight_ih_l0"]
    # Previous layout: P,T,missingP,missingT,sin,cos.
    # New layout:      P,T,missingP,missingT,logQ,missingQ,sin,cos.
    expanded = old_weight.new_zeros(old_weight.shape[0], old_weight.shape[1]+2)
    expanded[:, :4] = old_weight[:, :4]
    expanded[:, 6:] = old_weight[:, 4:]
    state["hindcast.weight_ih_l0"] = expanded
    parent["dimensions"][0] += 2
    parent["config"]["data"]["forecast_horizon"] = horizon
    parent["config"]["data"]["past_discharge"] = True
    parent["statistics"]["schema"]["past_discharge"] = True
    parent["transfer_adaptation"] = {
        "source_horizon": old_horizon, "new_horizon": horizon,
        "new_lead_initialization": "copy day-10 embedding; all lead embeddings trainable",
        "new_historical_channels": ["log_observed_discharge", "observed_discharge_missing"],
        "new_channel_initialization": "zero input weights; transferred calendar columns remapped",
        "all_other_weight_tensors_unchanged": True}
    return parent
