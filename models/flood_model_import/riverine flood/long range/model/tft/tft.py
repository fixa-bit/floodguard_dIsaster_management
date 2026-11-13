"""Temporal Fusion Transformer (Lim et al., 2021, Int. J. Forecasting 37(4)).

Compact single-entity implementation with the published components:
gated residual networks (GRN), variable selection networks (VSN), static
covariate encoders (4 contexts), LSTM encoder-decoder with gated skip,
static enrichment, interpretable multi-head attention (shared values,
causal mask), position-wise GRN and quantile outputs.

Missing targets are handled by the caller through a loss mask; missing past
discharge is passed as value 0 plus an explicit availability channel.
"""
from __future__ import annotations

import torch
from torch import nn
import torch.nn.functional as F


class GLU(nn.Module):
    def __init__(self, d_in, d_out):
        super().__init__()
        self.fc = nn.Linear(d_in, 2 * d_out)

    def forward(self, x):
        return F.glu(self.fc(x), dim=-1)


class GateAddNorm(nn.Module):
    def __init__(self, d, dropout):
        super().__init__()
        self.drop, self.glu, self.norm = nn.Dropout(dropout), GLU(d, d), nn.LayerNorm(d)

    def forward(self, x, residual):
        return self.norm(self.glu(self.drop(x)) + residual)


class GRN(nn.Module):
    def __init__(self, d_in, d_hidden, d_out, d_context=None, dropout=0.1):
        super().__init__()
        self.skip = nn.Linear(d_in, d_out) if d_in != d_out else nn.Identity()
        self.fc1 = nn.Linear(d_in, d_hidden)
        self.ctx = nn.Linear(d_context, d_hidden, bias=False) if d_context else None
        self.fc2 = nn.Linear(d_hidden, d_hidden)
        self.drop = nn.Dropout(dropout)
        self.glu = GLU(d_hidden, d_out)
        self.norm = nn.LayerNorm(d_out)

    def forward(self, x, context=None):
        h = self.fc1(x)
        if self.ctx is not None and context is not None:
            c = self.ctx(context)
            h = h + (c.unsqueeze(1) if h.dim() == 3 and c.dim() == 2 else c)
        h = self.fc2(F.elu(h))
        return self.norm(self.skip(x) + self.glu(self.drop(h)))


class RealEmbedding(nn.Module):
    """One linear embedding per scalar variable: (B, T, n) -> (B, T, n, d)."""

    def __init__(self, n, d):
        super().__init__()
        self.w = nn.Parameter(torch.randn(n, d) * 0.1)
        self.b = nn.Parameter(torch.zeros(n, d))

    def forward(self, x):
        return x.unsqueeze(-1) * self.w + self.b


class VSN(nn.Module):
    def __init__(self, n, d, dropout):
        super().__init__()
        self.flat = GRN(n * d, d, n, d_context=d, dropout=dropout)
        self.per_var = nn.ModuleList(GRN(d, d, d, dropout=dropout) for _ in range(n))

    def forward(self, emb, context):
        B, T, n, d = emb.shape
        weights = torch.softmax(self.flat(emb.reshape(B, T, n * d), context), dim=-1)  # (B,T,n)
        processed = torch.stack([g(emb[..., i, :]) for i, g in enumerate(self.per_var)], dim=-2)
        return (weights.unsqueeze(-1) * processed).sum(-2), weights


class InterpretableAttention(nn.Module):
    def __init__(self, d, heads, dropout):
        super().__init__()
        self.h, self.dk = heads, d // heads
        self.q = nn.ModuleList(nn.Linear(d, self.dk) for _ in range(heads))
        self.k = nn.ModuleList(nn.Linear(d, self.dk) for _ in range(heads))
        self.v = nn.Linear(d, self.dk)  # shared across heads
        self.out = nn.Linear(self.dk, d)
        self.drop = nn.Dropout(dropout)

    def forward(self, query, key, mask):
        v = self.v(key)
        heads, attn = [], []
        for q, k in zip(self.q, self.k):
            score = q(query) @ k(key).transpose(1, 2) / self.dk ** 0.5
            a = self.drop(torch.softmax(score.masked_fill(~mask, float("-inf")), dim=-1))
            heads.append(a @ v)
            attn.append(a)
        return self.out(torch.stack(heads).mean(0)), torch.stack(attn, 1).mean(1)


class TemporalFusionTransformer(nn.Module):
    def __init__(self, n_past, n_future, n_static_categories, d=64, heads=4, dropout=0.1, quantiles=(0.1, 0.5, 0.9)):
        super().__init__()
        self.quantiles = list(quantiles)
        self.static_emb = nn.Embedding(n_static_categories, d)
        self.static_grn = GRN(d, d, d, dropout=dropout)
        self.ctx = nn.ModuleDict({k: GRN(d, d, d, dropout=dropout) for k in ("select", "enrich", "h", "c")})
        self.past_emb, self.future_emb = RealEmbedding(n_past, d), RealEmbedding(n_future, d)
        self.past_vsn, self.future_vsn = VSN(n_past, d, dropout), VSN(n_future, d, dropout)
        self.encoder = nn.LSTM(d, d, batch_first=True)
        self.decoder = nn.LSTM(d, d, batch_first=True)
        self.lstm_gate = GateAddNorm(d, dropout)
        self.enrich = GRN(d, d, d, d_context=d, dropout=dropout)
        self.attention = InterpretableAttention(d, heads, dropout)
        self.attn_gate = GateAddNorm(d, dropout)
        self.positionwise = GRN(d, d, d, dropout=dropout)
        self.final_gate = GateAddNorm(d, dropout)
        self.head = nn.Linear(d, len(self.quantiles))

    def forward(self, past, future, static):
        """past (B,Te,n_past), future (B,Td,n_future), static (B,) long -> (B,Td,Q), interpretation."""
        s = self.static_grn(self.static_emb(static))
        c_sel, c_enr = self.ctx["select"](s), self.ctx["enrich"](s)
        h0, c0 = self.ctx["h"](s).unsqueeze(0), self.ctx["c"](s).unsqueeze(0)

        xp, wp = self.past_vsn(self.past_emb(past), c_sel)
        xf, wf = self.future_vsn(self.future_emb(future), c_sel)
        enc, state = self.encoder(xp, (h0.contiguous(), c0.contiguous()))
        dec, _ = self.decoder(xf, state)
        temporal = self.lstm_gate(torch.cat([enc, dec], 1), torch.cat([xp, xf], 1))
        enriched = self.enrich(temporal, c_enr)

        Te, Td = past.shape[1], future.shape[1]
        query = enriched[:, Te:]
        pos_q = torch.arange(Te, Te + Td, device=past.device).unsqueeze(1)
        pos_k = torch.arange(Te + Td, device=past.device).unsqueeze(0)
        mask = (pos_k <= pos_q).unsqueeze(0)  # causal: no peeking at later decoder steps
        attended, attn = self.attention(query, enriched, mask)
        x = self.attn_gate(attended, query)
        x = self.final_gate(self.positionwise(x), temporal[:, Te:])
        return self.head(x), {"past_weights": wp, "future_weights": wf, "attention": attn}


def quantile_loss(pred, target, mask, quantiles):
    """Pinball loss averaged over valid (mask==1) target cells only."""
    q = torch.tensor(quantiles, device=pred.device).view(1, 1, -1)
    diff = target.unsqueeze(-1) - pred
    loss = torch.maximum(q * diff, (q - 1) * diff)
    m = mask.unsqueeze(-1)
    return (loss * m).sum() / (m.sum() * len(quantiles)).clamp_min(1.0)
