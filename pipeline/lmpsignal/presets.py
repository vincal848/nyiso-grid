"""Post-processing presets and the frozen signal v1 definition (shared by `lmp post`, `lmp m7` and `lmp forecast`)."""
from __future__ import annotations

POST_PRESETS = {
    # name: (parent model names, steps)
    "lear_clip": (["lear"], [{"op": "clip"}, {"op": "calibrate", "method": "oos_residual"}]),
    "lear_clip_aci": (["lear"], [{"op": "clip"}, {"op": "calibrate", "method": "aci"}]),
    "gbm_l1_aci": (["gbm_l1"], [{"op": "calibrate", "method": "aci"}]),
    "combo_eq_aci": (["lear", "gbm_l1"], [{"op": "combine", "weights": "equal"}, {"op": "clip"},
                                          {"op": "calibrate", "method": "aci"}]),
    "combo_inv_aci": (["lear", "gbm_l1"], [{"op": "combine", "weights": "inv_mae"}, {"op": "clip"},
                                           {"op": "calibrate", "method": "aci"}]),
    "lear2_aci": (["lear2"], [{"op": "calibrate", "method": "aci"}]),
    "combo2_eq_aci": (["lear2", "gbm_l1"], [{"op": "combine", "weights": "equal"}, {"op": "clip"},
                                            {"op": "calibrate", "method": "aci"}]),
    "combo2_inv_aci": (["lear2", "gbm_l1"], [{"op": "combine", "weights": "inv_mae"}, {"op": "clip"},
                                             {"op": "calibrate", "method": "aci"}]),
    # M2.5 follow-ups
    "combo3_eq_aci": (["lear_clip", "gbm_l1"], [{"op": "combine", "weights": "equal"}, {"op": "clip"},
                                                {"op": "calibrate", "method": "aci"}]),
    # weather-corrected load + HRRR members (2026-10-04), mirroring lear_clip / gbm_l1_aci / combo3_eq_aci
    "lear_wx_clip": (["lear_wx"], [{"op": "clip"}, {"op": "calibrate", "method": "oos_residual"}]),
    "lear_wx_clip_aci": (["lear_wx"], [{"op": "clip"}, {"op": "calibrate", "method": "aci"}]),
    "gbm_l1_v3_aci": (["gbm_l1_v3"], [{"op": "calibrate", "method": "aci"}]),
    "combo3wx_eq_aci": (["lear_wx_clip", "gbm_l1_v3"], [{"op": "combine", "weights": "equal"}, {"op": "clip"},
                                                       {"op": "calibrate", "method": "aci"}]),
    # declared candidate of the training protocol (docs/ROADMAP.md): energy/loss from the better combo by pooled total
    # CRPS (combo3_eq_aci 7.593 vs combo3wx_eq_aci 7.606), congestion from lear2_long_aci, then ACI
    "assemble_v1_final": (["combo3_eq_aci", "lear2_long_aci"], [{"op": "assemble", "components": {
        "energy": "combo3_eq_aci", "loss": "combo3_eq_aci", "congestion": "lear2_long_aci"}},
        {"op": "calibrate", "method": "aci"}]),
    # M3b declared post variants (docs/ROADMAP.md): signal v1's RT total mixed with the spike member
    "v1_spike_mix": (["combo3_eq_aci", "spike_full"], [{"op": "spike_mix", "base": "combo3_eq_aci", "spike": "spike_full"}]),
    "v1_spike_mix_aci": (["combo3_eq_aci", "spike_full"], [{"op": "spike_mix", "base": "combo3_eq_aci", "spike": "spike_full"},
                                                           {"op": "calibrate", "method": "aci"}]),
    # M4 declared candidates (docs/ROADMAP.md)
    "combo3_med_aci": (["lear_clip", "gbm_l1", "persist_da_d1"], [{"op": "combine", "weights": "median"}, {"op": "clip"},
                                                                 {"op": "calibrate", "method": "aci"}]),
    "combo3_med_spike": (["combo3_med_aci", "spike_full"], [{"op": "spike_mix", "base": "combo3_med_aci",
                                                              "spike": "spike_full"}]),
    "lear2_long_aci": (["lear2"], [{"op": "windows", "use": ["w364", "w728", "wall"]},
                                   {"op": "calibrate", "method": "aci"}]),
    "assemble_v1e_v2c_aci": (["lear_clip", "lear2"], [{"op": "assemble", "components": {
        "energy": "lear_clip", "loss": "lear_clip", "congestion": "lear2"}}, {"op": "calibrate", "method": "aci"}]),
}


# Base-model constructors exactly as validated for signal v1 (docs/SIGNAL_V1.md). The validated LEAR run predates
# LEAR's internal clip option (clipping comes from the lear_clip post step), so it is LEAR(clip=False); verified to
# reproduce the stored validation predictions exactly (fold 2022-10, max abs diff 0).
FROZEN_BASES = {
    "lear": lambda: __import__("lmpsignal.models.lear", fromlist=["LEAR"]).LEAR(clip=False),
    "gbm_l1": lambda: __import__("lmpsignal.models.gbm", fromlist=["GBM"]).GBM(objective="l1"),
}

SIGNAL_V1 = "combo3_eq_aci"

# M5 (monthly DA products): the declared adoption rule kept the seasonal norm for both targets (ROADMAP, "M5 result").
M5_CHOICE = {"total": "m5_norm", "congestion": "m5_norm"}
