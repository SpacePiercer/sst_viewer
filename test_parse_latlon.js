// Run: node test_parse_latlon.js  -- parseLatLon (static/app.js): "lat, lon" | "lat lon" | "lat; lon"
const src = require("fs").readFileSync(__dirname + "/static/app.js", "utf8");
const fn = src.match(/function parseLatLon[\s\S]*?\r?\n\}\r?\n/)[0];
const parseLatLon = new Function(fn + "; return parseLatLon;")();
const assert = require("assert");
assert.deepStrictEqual(parseLatLon("49.3, -123.2"), [49.3, -123.2]);
assert.deepStrictEqual(parseLatLon("49.3 -123.2"), [49.3, -123.2]);
assert.deepStrictEqual(parseLatLon(" -5;170 "), [-5, 170]);
for (const bad of ["", "abc", "1,2,3", "91,0", "0,181", "5", "1e1, 2"]) assert.strictEqual(parseLatLon(bad), null, bad);
console.log("ok");
