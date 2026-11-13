"""Leakage and shape tests for the TFT.  Run: ../../.venv/Scripts/python.exe -m pytest test_tft.py"""
import torch

from tft import TemporalFusionTransformer, quantile_loss


def make():
    torch.manual_seed(0)
    return TemporalFusionTransformer(n_past=6, n_future=3, n_static_categories=2, d=16, heads=2, dropout=0.0).eval()


def test_shapes():
    out, interp = make()(torch.randn(4, 20, 6), torch.randn(4, 10, 3), torch.zeros(4, dtype=torch.long))
    assert out.shape == (4, 10, 3)
    assert torch.allclose(interp["past_weights"].sum(-1), torch.ones(4, 20))


def test_decoder_is_causal():
    """Changing a later decoder input must not change earlier decoder outputs."""
    m = make()
    past, fut, s = torch.randn(2, 20, 6), torch.randn(2, 10, 3), torch.zeros(2, dtype=torch.long)
    a, _ = m(past, fut, s)
    fut2 = fut.clone()
    fut2[:, 6:] += 5.0
    b, _ = m(past, fut2, s)
    assert torch.allclose(a[:, :6], b[:, :6], atol=1e-6)
    assert not torch.allclose(a[:, 6:], b[:, 6:])


def test_loss_ignores_masked_targets():
    pred = torch.zeros(1, 4, 3)
    y = torch.tensor([[1.0, 1.0, 1e6, 1e6]])
    mask = torch.tensor([[1.0, 1.0, 0.0, 0.0]])
    full = quantile_loss(pred[:, :2], y[:, :2], mask[:, :2], [0.1, 0.5, 0.9])
    assert torch.isclose(quantile_loss(pred, y, mask, [0.1, 0.5, 0.9]), full)
