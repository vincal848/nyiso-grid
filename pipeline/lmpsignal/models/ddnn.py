"""Distributional DNN with Johnson's SU output (DDNN-JSU; Marcjasz, Narajewski, Weron & Ziel 2023). M6 member.

Declared in docs/ROADMAP.md ("M6 declaration") before any run; the settings below are that declaration.
One network per market, pooled over locations. A sample is one location-day: the panel features of the 24 hours of D
(all as of 05:00 ET D-1; constant-within-day features simply repeat), location one-hot and weekday. The output is the
JSU parameters (xi, lambda, gamma, delta) for the 24 hours x 4 targets (total, energy, loss, congestion) in a
transformed space x = asinh((y - median) / MAD) with median and MAD per target from the fold's training data.
Four networks (seeds 0-3) per fold and market; quantiles are averaged across networks (qEns). Point forecast = mean
of the 1%..99% quantiles (trimmed mean). Tail guard: quantiles are clipped to the training range of the transformed
target (set in the fold-1 smoke test: without it the JSU-of-asinh tails reached $45,000/MWh on RT congestion). DST: the fall-back day's repeated hour shares one slot (inputs averaged, both
rows get the slot's forecast); the spring-forward day's missing slot is filled from its neighbours on input.
Needs the optional `deep` extra (torch).
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
from scipy.stats import norm

from lmpsignal.config import COMPONENTS, MARKETS
from lmpsignal.evaluate import QCOLS
from lmpsignal.models.base import ID_COLS, Model
from lmpsignal.panel import FEATURE_SETS

HIDDEN, DROPOUT, WEIGHT_DECAY, LR, BATCH = (512, 256), 0.1, 1e-5, 1e-3, 256
VAL_DAYS, PATIENCE, MAX_EPOCHS, SEEDS = 56, 20, 200, (0, 1, 2, 3)
GRID = np.round(np.arange(0.01, 1.0, 0.01), 2)                     # 99 quantiles for the trimmed mean
QS = np.array([float(c[1:]) / 100 for c in QCOLS])
NT, NH = len(COMPONENTS), 24


def _jsu_nll(x, xi, lam, gam, dlt):
    import torch

    u = (x - xi) / lam
    z = gam + dlt * torch.asinh(u)
    return -(torch.log(dlt) - torch.log(lam) - 0.5 * torch.log1p(u * u) - 0.5 * np.log(2 * np.pi) - 0.5 * z * z)


def jsu_quantiles(params: np.ndarray, qs: np.ndarray) -> np.ndarray:
    """params [..., 4] (xi, lambda, gamma, delta) -> quantiles [..., len(qs)] in the transformed space."""
    xi, lam, gam, dlt = (params[..., i:i + 1] for i in range(4))
    return xi + lam * np.sinh((norm.ppf(qs) - gam) / dlt)


class DDNN(Model):
    distributional = True                                          # runner keeps the model's own quantiles
    def __init__(self, feature_set: str = "v1", seeds=SEEDS, device: str | None = None, max_epochs: int = MAX_EPOCHS):
        self.feature_set = feature_set
        self.features = list(FEATURE_SETS[feature_set])
        self.seeds = tuple(seeds)
        self.max_epochs = max_epochs
        self.name = "ddnn" + ("" if feature_set == "v1" else f"_{feature_set}")
        self._device = device
        self._log: list[dict] = []

    def config(self) -> dict:
        return {"model": "DDNN-JSU (Marcjasz et al. 2023), pooled over locations, one network per market",
                "feature_set": self.feature_set, "hidden": HIDDEN, "dropout": DROPOUT, "weight_decay": WEIGHT_DECAY,
                "lr": LR, "batch": BATCH, "val_days": VAL_DAYS, "patience": PATIENCE, "max_epochs": self.max_epochs,
                "seeds": list(self.seeds), "ensemble": "quantile averaging (qEns)", "point": "mean of q01..q99",
                "target_transform": "asinh((y - median) / MAD) per target", "train_window": "all to train_end"}

    # ------------------------------------------------------------------ data shaping
    def _days(self, df: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
        """Index (zone, delivery_date) and the input tensor [n, F * 24] (unstandardized, NaN allowed)."""
        g = df.groupby(["zone", "delivery_date", "hour_local"])[self.features].mean()
        w = g.unstack("hour_local").reindex(columns=pd.MultiIndex.from_product([self.features, range(NH)]))
        arr = w.to_numpy(float).reshape(len(w), len(self.features), NH)
        arr = pd.DataFrame(arr.reshape(-1, NH)).ffill(axis=1).bfill(axis=1).to_numpy().reshape(arr.shape)
        idx = w.index.to_frame(index=False)
        return idx, arr.reshape(len(w), -1)

    def _design(self, idx: pd.DataFrame, X: np.ndarray) -> np.ndarray:
        Xs = (X - self._xm) / self._xs
        Xs = np.nan_to_num(Xs, nan=0.0, posinf=0.0, neginf=0.0)
        zone = (idx["zone"].to_numpy()[:, None] == np.array(self._zones)[None, :]).astype(float)
        dow = (pd.to_datetime(idx["delivery_date"]).dt.weekday.to_numpy()[:, None] == np.arange(7)[None, :]).astype(float)
        return np.hstack([Xs, zone, dow]).astype(np.float32)

    def _targets(self, df: pd.DataFrame, idx: pd.DataFrame, market: str) -> np.ndarray:
        cols = [f"{market}_{c}" for c in COMPONENTS]
        g = df.groupby(["zone", "delivery_date", "hour_local"])[cols].mean().unstack("hour_local")
        g = g.reindex(pd.MultiIndex.from_frame(idx)).reindex(columns=pd.MultiIndex.from_product([cols, range(NH)]))
        return g.to_numpy(float).reshape(len(idx), NT, NH)

    # ------------------------------------------------------------------ fit / predict
    def _net(self, n_in: int):
        import torch.nn as nn

        layers, d = [], n_in
        for h in HIDDEN:
            layers += [nn.Linear(d, h), nn.ReLU(), nn.Dropout(DROPOUT)]
            d = h
        layers.append(nn.Linear(d, NT * NH * 4))
        return nn.Sequential(*layers)

    def _params(self, out):
        import torch.nn.functional as F

        o = out.view(-1, NT, NH, 4)
        return o[..., 0], F.softplus(o[..., 1]) + 1e-3, o[..., 2], F.softplus(o[..., 3]) + 1e-3

    def _train_one(self, X: np.ndarray, T: np.ndarray, val: np.ndarray, seed: int):
        import torch

        torch.manual_seed(seed)
        rng = np.random.default_rng(seed)
        dev = self.device
        net = self._net(X.shape[1]).to(dev)
        opt = torch.optim.Adam(net.parameters(), lr=LR, weight_decay=WEIGHT_DECAY)
        Xt, Tt = torch.tensor(X, device=dev), torch.tensor(np.nan_to_num(T), dtype=torch.float32, device=dev)
        Mt = torch.tensor(~np.isnan(T), device=dev)
        tr_idx, va_idx = np.where(~val)[0], np.where(val)[0]

        def loss_on(ix, train: bool):
            net.train(train)
            xi, lam, gam, dlt = self._params(net(Xt[ix]))
            nll = _jsu_nll(Tt[ix], xi, lam, gam, dlt)
            m = Mt[ix]
            return (nll * m).sum() / m.sum().clamp(min=1)

        best, best_state, bad, epoch = np.inf, None, 0, 0
        for epoch in range(self.max_epochs):  # noqa: B007 (used after the loop)
            perm = rng.permutation(tr_idx)
            for s in range(0, len(perm), BATCH):
                ix = torch.tensor(perm[s:s + BATCH], device=dev)
                opt.zero_grad()
                loss = loss_on(ix, True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), 10.0)
                opt.step()
            with torch.no_grad():
                v = float(loss_on(torch.tensor(va_idx, device=dev), False))
            if v < best - 1e-4:
                best, bad = v, 0
                best_state = {k: t.detach().clone() for k, t in net.state_dict().items()}
            else:
                bad += 1
                if bad >= PATIENCE:
                    break
        net.load_state_dict(best_state)
        net.eval()
        return net, {"seed": seed, "best_val_nll": best, "epochs": epoch + 1}

    @property
    def device(self):
        import torch

        return self._device or ("cuda" if torch.cuda.is_available() else "cpu")

    def fit(self, train: pd.DataFrame) -> DDNN:
        t0 = time.time()
        idx, X = self._days(train)
        self._zones = sorted(train["zone"].unique())
        self._xm, self._xs = np.nanmean(X, axis=0), np.nanstd(X, axis=0)
        self._xs = np.where((self._xs > 0) & np.isfinite(self._xs), self._xs, 1.0)
        self._xm = np.nan_to_num(self._xm)
        D = self._design(idx, X)
        dates = pd.to_datetime(idx["delivery_date"])
        val = (dates > dates.max() - pd.Timedelta(days=VAL_DAYS)).to_numpy()
        self.nets, self.scale, self._log = {}, {}, []
        for m in MARKETS:
            Y = self._targets(train, idx, m)
            med = np.nanmedian(Y, axis=(0, 2))
            mad = np.nanmedian(np.abs(Y - med[None, :, None]), axis=(0, 2))
            sd = np.nanstd(Y, axis=(0, 2))
            mad = np.maximum.reduce([mad, 0.1 * sd, np.full_like(mad, 0.5)])
            T = np.arcsinh((Y - med[None, :, None]) / mad[None, :, None]).astype(np.float32)
            self.scale[m] = (med, mad, np.nanmin(T, axis=(0, 2)), np.nanmax(T, axis=(0, 2)))
            self.nets[m] = []
            for seed in self.seeds:
                net, info = self._train_one(D, T, val, seed)
                self.nets[m].append(net)
                self._log.append({"market": m, **info})
        self._fit_s = time.time() - t0
        return self

    def predict(self, test: pd.DataFrame) -> pd.DataFrame:
        import torch

        idx, X = self._days(test)
        D = torch.tensor(self._design(idx, X), device=self.device)
        qs_all = np.concatenate([QS, GRID])
        parts = []
        for m in MARKETS:
            med, mad, xmin, xmax = self.scale[m]
            Q = 0.0
            with torch.no_grad():
                for net in self.nets[m]:
                    xi, lam, gam, dlt = (t.cpu().numpy() for t in self._params(net(D)))
                    P = np.stack([xi, lam, gam, dlt], axis=-1)                         # [n, NT, NH, 4]
                    q = jsu_quantiles(P, qs_all)                                        # [n, NT, NH, nq]
                    Q = Q + np.clip(q, xmin[None, :, None, None], xmax[None, :, None, None])
            Q = Q / len(self.nets[m])
            Y = med[None, :, None, None] + mad[None, :, None, None] * np.sinh(Q)       # back to $/MWh
            nq = len(QS)
            Y = np.concatenate([np.sort(Y[..., :nq], axis=-1), Y[..., nq:]], axis=-1)   # sort the output quantiles only
            for k, c in enumerate(COMPONENTS):
                arr = Y[:, k]                                                           # [n, NH, nq]
                rows = idx.loc[np.repeat(np.arange(len(idx)), NH)].reset_index(drop=True)
                rows["hour_local"] = np.tile(np.arange(NH), len(idx))
                flat = arr.reshape(-1, arr.shape[-1])
                rows[QCOLS] = flat[:, :len(QS)]
                rows["mean"] = flat[:, len(QS):].mean(axis=1)
                parts.append(rows.assign(market=m, component=c))
        f = pd.concat(parts, ignore_index=True)
        base = test[ID_COLS + ["hour_local"]]
        out = base.merge(f, on=["zone", "delivery_date", "hour_local"], how="left")
        return out[ID_COLS + ["hour_local", "market", "component", "mean", *QCOLS]]

    def artifacts(self) -> dict[str, pd.DataFrame]:
        return {"training": pd.DataFrame(self._log).assign(fit_seconds=getattr(self, "_fit_s", np.nan))}
