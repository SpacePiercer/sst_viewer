"""Charts are gone; map popup feeds the Data tab. Run: python test_point_to_data.py"""
from pathlib import Path
import app as A

S = Path(__file__).parent / "static"
paths = {r.path for r in A.app.routes}
assert "/api/series" not in paths and not any("mean_series" in p for p in paths)
html, js = (S / "index.html").read_text(encoding="utf-8"), (S / "app.js").read_text(encoding="utf-8")
assert "chartPanel" not in html and "chart.js" not in html and "chartPoint" not in js
assert "addPointToData" in js and "addCoordsFromText();" in js
print("ok")
