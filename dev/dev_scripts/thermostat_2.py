"""
utils/poll_trv_params.py
���������
Poll Danfoss Ally TRVs for the control-loop parameters and show what
keys are actually present in each thermostat�s JSON.
"""

from __future__ import annotations
import json
from typing import Dict, Iterable, Any

from utils.project import (
    get_thermostat_state_by_id,   # returns raw JSON or selected leaves
    report                        # your logging shim
)  # :contentReference[oaicite:0]{index=0}

# -- 1.  All spellings we have seen in the wild --------------------------------
ALIASES: dict[str, list[str]] = {
    "algorithm_scale_factor":  ["algorithm_scale_factor",
                                "algorithmscalefactor",
                                "algorithmScaleFactor"],
    "radiator_covered":        ["radiator_covered",
                                "radiatorcovered",
                                "radiatorCovered"],
    "adaptation_run_status":   ["adaptation_run_status",
                                "adaptationrunstatus",
                                "adaptationRunStatus"],
    "mounting_mode_active":    ["mounting_mode_active",
                                "mountingmodeactive",
                                "mountingModeActive"],
}

# -- 2.  Helper to decode scale-factor ? {scale, quick_open_enabled} -----------
def _decode_algo(raw: int | None) -> Dict[str, Any]:
    if raw is None:
        return {"scale": None, "quick_open_enabled": None}
    return {
        "scale": raw & 0x0F,                 # 1-10
        "quick_open_enabled": (raw & 0x10) == 0,   # bit-4 cleared ? enabled
    }

# -- 3.  Little finder that searches config ? state ? root --------------------
def _find(raw: dict, names: list[str]) -> Any:
    cfg   = raw.get("config", {})
    state = raw.get("state", {})
    for n in names:
        if n in cfg:
            return cfg[n]
        if n in state:
            return state[n]
        if n in raw:
            return raw[n]
    return None

# -- 4.  Public polling function ----------------------------------------------
def poll_trvs(trv_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    snapshot: Dict[str, Dict[str, Any]] = {}
    for tid in trv_ids:
        try:
            raw = get_thermostat_state_by_id(tid)   # full JSON, no fields list
            rec = {key: _find(raw, names)           # try every alias
                   for key, names in ALIASES.items()}

            rec["decoded"]      = _decode_algo(rec["algorithm_scale_factor"])
            rec["config_keys"]  = sorted(raw.get("config", {}).keys())
            rec["state_keys"]   = sorted(raw.get("state", {}).keys())

            snapshot[tid] = rec

        except Exception as exc:                    # keep going on errors
            report(f"[TRV {tid}] polling failed � {exc}")
            snapshot[tid] = {"error": str(exc)}

    return snapshot

# -- 5.  Handy CLI use ---------------------------------------------------------
if __name__ == "__main__":
    MY_TRVS = ["71", "75", "63", "65", "53", "57"]    # ? your IDs here
    print(json.dumps(poll_trvs(MY_TRVS), indent=2, sort_keys=True))
