"""Self-check for the MUR gap estimate (reports.interp_estimates). Offline.
Run: conda run -n mfa_env python test_mur_interp.py
"""
import reports as R

valid = {"2016-06-30": 10.0, "2016-07-02": 12.0,   # both sides of 07-01
         "2016-07-04": 11.0,                        # 07-03 sits between 07-02 and 07-04
         "2016-07-09": 9.0}                         # 07-10: day+1 missing -> no estimate
bad = ["2016-07-01", "2016-07-03", "2016-07-10", "2016-07-20"]
out = R.interp_estimates(bad, valid, {"2016-07-01": 12.49}).set_index("date")

assert list(out.index) == ["2016-07-01", "2016-07-03"]       # one-sided / no neighbours -> absent
assert out.loc["2016-07-01", "estimate"] == 11.0
assert out.loc["2016-07-01", "oisst"] == 12.49
assert (out.loc["2016-07-01", "mur_prev"], out.loc["2016-07-01", "mur_next"]) == (10.0, 12.0)
assert out.loc["2016-07-03", "estimate"] == 11.5 and out.loc["2016-07-03", "oisst"] != out.loc["2016-07-03", "oisst"]  # NaN
assert R.interp_estimates([], valid, {}).empty
print("mur interp self-check: OK")
