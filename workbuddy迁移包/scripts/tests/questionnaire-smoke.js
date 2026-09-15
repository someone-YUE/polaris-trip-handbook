// 问卷页逻辑烟测：在 Node 里用极简 DOM stub 跑 collect() + promptText() + validateBrief()
// 目的：验证新问卷（目的地+途经城、时段选择、晚数自动推导、同行下拉、节奏自由文本、
// 比价口径滑块）真的能产出正确 brief，而不只是语法通过。
const fs = require("fs");
const path = require("path");
const assert = require("assert");

const htmlPath = process.argv[2];
const html = fs.readFileSync(htmlPath, "utf8");
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) throw new Error("没找到 <script> 块");
let js = scriptMatch[1];

// ---- 极简 DOM stub ----
const values = {
  "f-origin": "北京", "f-dest": "天津",
  "f-start": "2027-03-12", "f-start-period": "evening", "f-start-time": "18:30",
  "f-end": "2027-03-16", "f-end-period": "morning", "f-end-time": "08:20",
  "f-count": "1", "f-rooms": "1",
  "f-groups-sel": "独自出行", "f-groups-custom": "",
  "f-wake": "08:00 前（周末自然醒）", "f-sleep": "23:30 前",
  "f-rhythm": "不想赶，一天一两个重点，主打逛吃，晚上去夜市；愿意为好吃的排一小时队。",
  "f-tp-pref": "prefer-rail",
  "f-tp-profile": "0", // 滑块值 0 = thrifty
  "f-transport": "",
  "f-budget": "¥200-350/间/晚",
  "f-mustgo": "示例博物馆,示例公园",
  "f-avoid": "过度辛辣",
  "f-notes": "一人不太能吃辣",
};

// 途经城市：济南 2 晚（真实 DOM 里由 addViaRow 生成，这里直接造行对象）
const viaRows = [{ city: "济南", nights: "2", area: "泉城广场" }];

const els = {};
function makeEl(id) {
  return {
    id, value: values[id] !== undefined ? values[id] : "",
    style: {},
    classList: { add() {}, remove() {}, contains() { return false; } },
    addEventListener() {}, scrollIntoView() {},
    querySelector() { return makeEl(""); },
    querySelectorAll() { return []; },
    set innerHTML(v) {}, get innerHTML() { return ""; },
    set textContent(v) { this._t = v; }, get textContent() { return this._t; },
    appendChild() {}, remove() {},
  };
}
global.document = {
  getElementById(id) { return (els[id] = els[id] || makeEl(id)); },
  querySelectorAll(sel) {
    if (sel === "#f-interests input:checked")
      return [{ value: "夜市", checked: true }, { value: "老街", checked: true }];
    if (sel === "#f-vias .cityrow") return viaRows.map((v) => ({
      querySelector(q) {
        if (q === ".via-city") return { value: v.city };
        if (q === ".via-nights") return { value: v.nights };
        if (q === ".via-area") return { value: v.area };
        return { value: "" };
      },
    }));
    if (sel === "#f-interests input") return [];
    if (sel === "#f-vias .cityrow") return [];
    return [];
  },
  querySelector() { return null; },
  createElement() { return makeEl("dyn"); },
  body: { appendChild() {}, removeChild() {} },
  addEventListener() {},
  execCommand() { return true; },
};
global.localStorage = {
  _d: {}, getItem(k) { return this._d[k] || null; },
  setItem(k, v) { this._d[k] = v; }, removeItem(k) { delete this._d[k]; },
};
global.navigator = {};
global.confirm = () => true;
global.URL = { createObjectURL: () => "blob:x" };
global.Blob = function () {};
global.setTimeout = (fn) => 0;
global.clearTimeout = () => {};
global.Date = Date;

// ---- 让脚本把内部函数暴露出来：在 IIFE 结束前注入导出 ----
const tailIdx = js.lastIndexOf("})();");
if (tailIdx < 0) throw new Error("没找到 IIFE 结尾");
js = js.slice(0, tailIdx)
  + "\n  globalThis.__test = { collect, promptText, validateBrief, deriveNights };\n"
  + js.slice(tailIdx);
eval(js);

const { collect, promptText, validateBrief, deriveNights } = globalThis.__test;
const brief = collect();

console.log("=== deriveNights() ===");
console.log(JSON.stringify(deriveNights(), null, 2));
console.log("\n=== collect() ===");
console.log(JSON.stringify(brief, null, 2));
console.log("\nvalidateBrief:", validateBrief(brief));

console.log("\n=== promptText() ===");
console.log(promptText(brief));

// ---- 断言 ----
// 1. 途经城市 + 目的地合成 route，晚数按日期跨度自动摊分
assert.deepStrictEqual(brief.route, [
  { city: "济南", nights: 2, area: "泉城广场" },
  { city: "天津", nights: 2 },
], "route 应由「途经城 + 目的地」合成，晚数自动推导（03-12~03-16 = 5 天 4 晚）");

// 2. 时段与具体时间进入 preferences
assert.strictEqual(brief.preferences.start_period, "evening", "出发时段应被读出");
assert.strictEqual(brief.preferences.start_time, "18:30", "出发具体时间应被读出");
assert.strictEqual(brief.preferences.end_period, "morning", "返程时段应被读出");
assert.strictEqual(brief.preferences.end_time, "08:20", "返程具体时间应被读出");

// 3. 同行关系来自下拉；独自出行 → 人数 1
assert.strictEqual(brief.travelers.groups, "独自出行", "同行关系应来自下拉菜单");
assert.strictEqual(brief.travelers.count, 1, "独自出行人数应为 1");

// 4. 节奏是自由文本原话
assert.ok(brief.trip.rhythm.includes("逛吃"), "节奏应保留用户自由文本原话");

// 5. 滑块数值映射回三档 key
assert.strictEqual(brief.preferences.transport_profile, "thrifty", "滑块 0 应映射为 thrifty");
assert.strictEqual(brief.preferences.transport_preference, "prefer-rail", "倾向应被读出");

// 6. 预算改名后仍写入 preferences.budget
assert.strictEqual(brief.preferences.budget, "¥200-350/间/晚", "预算字段应保留");

// 7. 校验通过 + 提示词包含关键段
assert.deepStrictEqual(validateBrief(brief), [], "完整问卷不应有校验错误");
const pt = promptText(brief);
assert.ok(pt.includes("【同行与作息】"), "提示词应含同行与作息段");
assert.ok(pt.includes("你想怎么玩"), "提示词应含「你想怎么玩」");
assert.ok(pt.includes("下班后出发"), "提示词应提示下班后出发");
assert.ok(pt.includes("上班前回来"), "提示词应提示返程赶上班");
assert.ok(pt.includes("（途经）"), "提示词应标注途经城市");
assert.ok(pt.includes("（目的地）"), "提示词应标注目的地");
assert.ok(pt.includes("transport-fares.json"), "提示词应提示价表位置");

console.log("\n✅ 问卷逻辑烟测全部通过");
