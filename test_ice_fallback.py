"""Self-check for the MUR false-summer-ice fallback (reports.apply_ice_fallback).
Offline, no network. Run: conda run -n mfa_env python test_ice_fallback.py
"""
import pandas as pd

import reports as R

dates = ["2016-04-30", "2016-07-01", "2016-07-02", "2016-07-03", "2016-07-04", "2017-07-01"]
mur = pd.DataFrame({"date": dates, "value": [-1.8, -1.8, -1.8, -1.8, 12.0, 13.0]})
mur["sst_celsius"] = mur["value"]
mur["md"] = mur["date"].str[5:]
mur["dataset"] = "MUR"

mur_ice = {"2016-04-30": 0.9, "2016-07-01": 0.68, "2016-07-02": 0.7, "2016-07-03": 0.7}
oisst_ice = {"2016-07-02": 0.4}                      # OISST agrees: real ice
oisst_sst = {"2016-04-30": -1.5, "2016-07-01": 12.49, "2016-07-02": -1.8}  # 07-03: none

out = R.apply_ice_fallback(mur, mur_ice, oisst_ice, oisst_sst).set_index("date")

# summer MUR ice, OISST open water -> OISST value, tagged
assert out.loc["2016-07-01", "sst_celsius"] == 12.49
assert out.loc["2016-07-01", "value"] == 12.49
assert out.loc["2016-07-01", "dataset"] == "OISST"
# outside May-Sep the MUR ice is kept as is
assert out.loc["2016-04-30", "sst_celsius"] == -1.8 and out.loc["2016-04-30", "dataset"] == "MUR"
# both datasets show ice -> keep MUR
assert out.loc["2016-07-02", "sst_celsius"] == -1.8 and out.loc["2016-07-02", "dataset"] == "MUR"
# MUR ice, OISST open water but no OISST value -> no data, row dropped
assert "2016-07-03" not in out.index
# no MUR ice -> untouched
assert out.loc["2016-07-04", "sst_celsius"] == 12.0 and out.loc["2016-07-04", "dataset"] == "MUR"
# anomaly recomputed from the substituted values (07-01: 12.49 vs 13.0)
assert abs(out.loc["2016-07-01", "sst_anomaly"] - (12.49 - (12.49 + 13.0) / 2)) < 1e-9
# input frame not mutated
assert mur.loc[1, "sst_celsius"] == -1.8

print("ice fallback self-check: OK")
