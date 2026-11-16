// Run: node test_timelapse_range.js  -- mergeRange (static/app.js) = min of lows, max of highs
const src = require("fs").readFileSync(__dirname + "/static/app.js", "utf8");
const fn = src.match(/function mergeRange[\s\S]*?\r?\n\}\r?\n/)[0];
const mergeRange = new Function(fn + "; return mergeRange;")();
const assert = require("assert");
assert.deepStrictEqual(mergeRange([[-1, 6.5], [8, 14.2], [NaN, 3], null]), [-1, 14.2]);
assert.strictEqual(mergeRange([]), null);
console.log("ok");
