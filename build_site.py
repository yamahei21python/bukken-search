"""静的サイト生成: 選別結果を site/ へ出力する (Vercel/GitHub Pages 用)。

Streamlit は常駐プロセスが必要で Vercel (サーバーレス) では動かない。
そこで app_data と同じ計算経路 (絞り込み→公正価値→割安度) を
ビルド時に実行し、結果 JSON + 単一 HTML を静的に吐き出す。
main への push (毎朝のスクレイプ) で Vercel が自動更新する。

使い方:
  python3 build_site.py          # site/ を生成
出力:
  site/index.html  一覧テーブル + Leaflet マップ (CDN)
  site/data.json   行データ (生成日時・モデル指標つき)
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import app_data

OUT = Path(__file__).parent / "site"


def _num(v):
    """JSON 用に NaN を None へ。"""
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def build_rows(out):
    """DataFrame をテーブル/マップ用のコンパクトな dict 列へ。"""
    rows = []
    for r in out.itertuples():
        rows.append({
            "n": r.name, "st": r.station, "w": _num(r.walk_min),
            "l": r.layout, "a": _num(r.area_m2), "f": _num(r.room_floor),
            "y": _num(r.age_years), "tot": r.total_yen,
            "fair": _num(round(r.fair)),
            "disc": _num(round(r.discount * 100, 1)),
            "eff": _num(round(r.eff_monthly)) if pd.notna(r.eff_monthly) else None,
            "t2": _num(round(r.t2)) if pd.notna(r.t2) else None,
            # 湯船判定は検索戦略が推測できるため公開データには含めない
            # (自家用の Streamlit app のみに表示)
            "eq": "" if pd.isna(r.equipment) else str(r.equipment)[:120],
            "url": r.detail_url,
            "lat": _num(r.b_lat), "lon": _num(r.b_lon),
        })
    return rows


def build(out_dir=OUT):
    """site/ を生成する。out_dir はテストで tmp に差し替え可能。"""
    df = app_data.load_df()
    fdf = app_data.apply_filters(df)
    out, meta = app_data.add_fair_value(fdf)
    out = out.sort_values("discount", ascending=False)
    rows = build_rows(out)
    payload = {
        "generated_at": datetime.now(timezone.utc)
        .strftime("%Y-%m-%d %H:%M UTC"),
        "meta": {
            "rows": len(rows),
            "r2": meta.get("r2"),
            "mae_yen": meta.get("mae_yen"),
        },
        "rows": rows,
    }
    out_dir.mkdir(exist_ok=True)
    (out_dir / "data.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    (out_dir / "index.html").write_text(_TEMPLATE)
    print(f"site: {len(rows)} rows -> {out_dir/'data.json'}"
          f" ({(out_dir/'data.json').stat().st_size / 1e6:.1f}MB)")
    return len(rows)


_TEMPLATE = """<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>阿波座 賃貸選別 (静的版)</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
body{font-family:system-ui,-apple-system,"Hiragino Sans",sans-serif;
  margin:0;background:#f6f7f9;color:#1c2430}
header{padding:12px 16px;background:#0d2f5a;color:#fff}
header h1{font-size:16px;margin:0 0 4px}
header .meta{font-size:11px;opacity:.75}
#filters{display:flex;flex-wrap:wrap;gap:10px;align-items:center;
  padding:10px 16px;background:#fff;border-bottom:1px solid #e2e6ec;
  font-size:13px;position:sticky;top:0;z-index:900}
#filters label{display:flex;gap:4px;align-items:center}
#filters input[type=text]{width:140px}
#tabs{display:flex;gap:8px;padding:8px 16px 0}
#tabs button{border:1px solid #c9d2de;background:#fff;border-radius:6px;
  padding:6px 14px;font-size:13px;cursor:pointer}
#tabs button.on{background:#0d2f5a;color:#fff;border-color:#0d2f5a}
#tblwrap{overflow:auto;max-height:70vh;padding:8px 16px}
table{border-collapse:collapse;width:100%;font-size:12.5px;background:#fff}
th,td{border-bottom:1px solid #e8ecf1;padding:5px 7px;text-align:left;
  white-space:nowrap}
th{position:sticky;top:0;background:#eef2f7;cursor:pointer;user-select:none}
tr:hover td{background:#f2f7ff}
td.url a{color:#0d5bd8}
.disc{font-weight:700;color:#c0392b}
.tag{font-size:10px;border-radius:4px;padding:1px 5px;color:#fff}
#map{height:70vh;margin:8px 16px;border-radius:8px}
#hint{padding:2px 16px;font-size:11px;color:#69748a}
</style>
</head>
<body>
<header>
  <h1>阿波座 賃貸選別 <span id="cnt"></span></h1>
  <div class="meta" id="meta"></div>
</header>
<div id="filters">
  <label>総額上限 <input type="range" id="f_tot" min="50000" max="100000"
    step="5000" value="100000" oninput="render()"><span id="f_tot_v"></span></label>
  <label>徒歩 <input type="number" id="f_walk" value="10" min="1" max="20"
    style="width:52px" oninput="render()">分</label>
  <label><input type="checkbox" id="f_eff">実質月額あるのみ</label>
  <label>検索 <input type="text" id="f_q" oninput="render()"
    placeholder="建物名・設備"></label>
  <span>ソート:
    <select id="f_sort" onchange="render()">
      <option value="disc">割安度</option><option value="tot">総額</option>
      <option value="eff">実質月額</option><option value="t2">2年総額</option>
    </select></span>
  <span>表示:
    <select id="f_limit" onchange="render()">
      <option value="50">50件</option>
      <option value="100" selected>100件</option>
      <option value="300">300件</option>
      <option value="1000">1000件</option>
      <option value="0">全件</option>
    </select></span>
</div>
<div id="tabs">
  <button id="tab_t" class="on" onclick="tab('t')">一覧</button>
  <button id="tab_m" onclick="tab('m')">マップ</button>
</div>
<div id="tblwrap"><table id="tbl"><thead></thead><tbody></tbody></table></div>
<div id="map"></div>
<div style="padding:0 16px;font-size:11px;color:#69748a">
  マップ: 表示件数セレクタに連動 (既定=割安上位100件)。
  割安度が高いほど大きく・赤く (青=低 → 赤=高。赤の上限は上位5%起点で自動調整)</div>
<div id="hint">静的生成のため値下げ等の即時性はスクレイプ時点 (毎朝)。
詳細は SUUMO リンクで確認。</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
let DATA, MAP, LAYER;
fetch("data.json").then(r => r.json()).then(d => {
  DATA = d;
  document.getElementById("meta").textContent =
    `生成 ${d.generated_at} / 母数 ${d.meta.rows.toLocaleString()} 件 / `
    + `モデル CV R2=${(d.meta.r2 ?? 0).toFixed(3)} MAE=${Math.round(d.meta.mae_yen ?? 0).toLocaleString()}円`;
  render();
  initMap();
});
function tab(t) {
  document.getElementById("tab_t").classList.toggle("on", t === "t");
  document.getElementById("tab_m").classList.toggle("on", t === "m");
  document.getElementById("tblwrap").style.display = t === "t" ? "" : "none";
  document.getElementById("map").style.display = t === "m" ? "" : "none";
  if (t === "m" && MAP) setTimeout(() => MAP.invalidateSize(), 50);
}
function filtered() {
  const tot = +document.getElementById("f_tot").value;
  const walk = +document.getElementById("f_walk").value;
  const effOnly = document.getElementById("f_eff").checked;
  const q = document.getElementById("f_q").value.trim();
  const sort = document.getElementById("f_sort").value;
  let rows = DATA.rows.filter(r =>
    r.tot <= tot && r.w != null && r.w <= walk
    && (!effOnly || r.eff != null)
    && (!q || (r.n + r.eq + r.st).includes(q)));
  const key = sort === "disc" ? "disc" : sort;
  rows.sort((a, b) => (b[key] ?? -1) - (a[key] ?? -1));
  return rows;
}
function displayed() {
  const limit = +document.getElementById("f_limit").value;
  const rows = filtered();
  return limit > 0 ? rows.slice(0, limit) : rows;
}
function render() {
  const rows = filtered();
  document.getElementById("f_tot_v").textContent =
    (document.getElementById("f_tot").value / 10000) + "万";
  document.getElementById("cnt").textContent = `hit ${rows.length.toLocaleString()}件`;
  const thead = document.getElementById("tbl").tHead;
  thead.innerHTML = "<tr><th>割安%</th><th>総額</th><th>実質</th><th>2年</th>"
    + "<th>間取</th><th>面積</th><th>階</th><th>築</th><th>徒歩</th>"
    + "<th>駅</th><th>建物</th><th>設備</th><th>リンク</th></tr>";
  const tb = document.getElementById("tbl").tBodies[0];
  const shown = displayed();
  tb.innerHTML = shown.map(r => {
    return `<tr><td class="disc">${r.disc ?? "-"}</td>`
      + `<td>${(r.tot / 10000).toFixed(1)}万</td>`
      + `<td>${r.eff ? (r.eff / 10000).toFixed(2) + "万" : "-"}</td>`
      + `<td>${r.t2 ? (r.t2 / 10000).toFixed(0) + "万" : "-"}</td>`
      + `<td>${r.l || "-"}</td><td>${r.a ?? "-"}</td><td>${r.f ?? "-"}</td>`
      + `<td>${r.y ?? "-"}</td><td>${r.w ?? "-"}</td><td>${r.st || "-"}</td>`
      + `<td>${r.n}</td><td>${r.eq}</td>`
      + `<td class="url"><a href="${r.url}" target="_blank" rel="noopener">SUUMO</a></td></tr>`;
  }).join("");
  if (shown.length < rows.length) {
    tb.insertAdjacentHTML("beforeend",
      `<tr><td colspan=13>… 先頭${shown.length}件のみ表示`
      + ` (条件に合うのは全${rows.length}件)。</td></tr>`);
  }
}
function initMap() {
  MAP = L.map("map").setView([34.6815, 135.4953], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {attribution: "© OpenStreetMap"}).addTo(MAP);
  LAYER = L.layerGroup().addTo(MAP);
  drawMap();
}
function drawMap() {
  if (!LAYER) return;
  LAYER.clearLayers();

  // 地図も「表示」セレクタの上位N件に連動 (全件だと重く視認性も低下)
  const rows = displayed().filter(r => r.lat != null && r.lon != null);
  const discs = rows.map(r => r.disc ?? 0).sort((a, b) => a - b);
  const dmax = discs.length ? discs[Math.floor(discs.length * 0.95)] : 0;
  const scale = v => Math.max(0, Math.min(1, v / Math.max(dmax, 1)));
  for (const r of rows) {
    const t = scale(r.disc ?? 0);
    // 割安度が高いほど赤く・大きく (青→赤のグラデーション)
    L.circleMarker([r.lat, r.lon], {radius: 4 + 7 * t,
      color: `hsl(${210 - 210 * t}, 70%, 42%)`,
      fillColor: `hsl(${210 - 210 * t}, 70%, 55%)`, fillOpacity: .8,
      weight: 1})
      .bindPopup(`<b>${r.n}</b><br>割安 <b>${r.disc ?? "-"}%</b> `
        + `(公正${r.fair ? (r.fair / 10000).toFixed(1) + "万" : "-"} /`
        + ` 実${(r.tot / 10000).toFixed(1)}万)`
        + `<br>${r.l} ${r.a}m2 ${r.st} 歩${r.w}分`
        + `<br><a href="${r.url}" target="_blank" rel="noopener">SUUMO</a>`)
      .addTo(LAYER);
  }
}
document.getElementById("f_eff").addEventListener("change", () => {
  render();
  drawMap();
});
document.getElementById("f_limit").addEventListener("change", () => {
  render();
  drawMap();
});
document.getElementById("f_sort").addEventListener("change", () => {
  render();
  drawMap();
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
