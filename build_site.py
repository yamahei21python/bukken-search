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
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import app_data

OUT = Path(__file__).parent / "site"

# Google Maps JavaScript API のキー (任意)。
# 設定があれば普段使いの Google マップで描画し、無ければ Leaflet (OSM)。
# キーは GCP で発行し、HTTP リファラー制限 (自分の Vercel ドメイン等)
# を掛けてから使う (静的サイトでは HTML に含まれるため必ず制限する)。
GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")


# SUUMO のカセット見出しに建物名が未登録の掲載は「路線 駅 N階建
# 築N年」が物件名として入ってくる (約1,100名)。建物名として意味が
# 無いため公開サイトでは表示しない (DB の元データは保持したまま)。
_POLLUTED_NAME = re.compile(
    r"^(?:\S+線|\S+電鉄|\S+メトロ\S*)\s+\S+駅\s+"
    r"(?:地下\d+)?(?:地上\d+)?\d+階建\s+(?:築\S+|新築)$")
_UNNAMED = "(建物名未登録)"


def _display_name(n):
    """汚染見出しを (建物名未登録) に置き換える表示用マスキング。"""
    n = (n or "").strip()
    return _UNNAMED if _POLLUTED_NAME.match(n) else n


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
            "n": _display_name(r.name), "st": r.station,
            "w": _num(r.walk_min),
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
    # 汚染見出しの建物名を部屋照合で実名に復元 (表示のみ)
    out = app_data.resolve_display_names(out)
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
    (out_dir / "index.html").write_text(
        _TEMPLATE.replace("__GKEY__", GOOGLE_MAPS_API_KEY))
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
<script>window.GKEY = "__GKEY__";</script>
<style>
body{font-family:system-ui,-apple-system,"Hiragino Sans",sans-serif;
  margin:0;background:#f6f7f9;color:#1c2430}
header{padding:12px 16px;background:#0d2f5a;color:#fff}
header h1{font-size:16px;margin:0 0 4px}
header .meta{font-size:11px;opacity:.75}
header .legend{font-size:10.5px;opacity:.6;margin-top:4px;line-height:1.5}
#filters{display:flex;flex-wrap:wrap;gap:10px;align-items:center;
  padding:10px 16px;background:#fff;border-bottom:1px solid #e2e6ec;
  font-size:13px;position:sticky;top:0;z-index:900}
#filters label{display:flex;gap:4px;align-items:center}
.dd{position:relative}
.dd-btn{border:1px solid #c9d2de;background:#fff;border-radius:6px;
  padding:4px 10px;font-size:12.5px;cursor:pointer}
.dd.open .dd-btn{background:#0d2f5a;color:#fff;border-color:#0d2f5a}
.dd-panel{display:none;position:absolute;top:110%;left:0;z-index:1000;
  background:#fff;border:1px solid #c9d2de;border-radius:6px;
  box-shadow:0 4px 12px rgba(0,0,0,.14);padding:8px 10px;
  max-height:300px;overflow:auto;min-width:150px}
.dd.open .dd-panel{display:block}
.dd-panel label{display:block;padding:3px 2px;font-size:12.5px;
  white-space:nowrap;gap:6px}
#filters input[type=text]{width:140px}
#tabs{display:flex;justify-content:center;gap:8px;padding:8px 16px 0}
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
  <div class="legend">総額=毎月の賃料+管理費 / 実質=総額+毎月固定費+初期費用・更新料を2年で平準化した月額
    / 2年=2年間の総支出(初期費用・敷金込み、フリーレント控除)
    / 割安%=公正価値(同条件の予測適正額)より総額が安い割合 / 金額は万円単位</div>
</header>
<div id="filters">
  <label>総額上限 <input type="range" id="f_tot" min="50000" max="100000"
    step="5000" value="100000" oninput="render()"><span id="f_tot_v"></span></label>
  <label>徒歩 <input type="number" id="f_walk" value="10" min="1" max="20"
    style="width:52px" oninput="render()">分</label>
  <label><input type="checkbox" id="f_eff">実質月額あるのみ</label>
  <div class="dd">
    <button type="button" class="dd-btn" id="dd_lo_btn">間取り ▾</button>
    <div class="dd-panel" id="f_layouts"></div>
  </div>
  <div class="dd">
    <button type="button" class="dd-btn" id="dd_st_btn">駅 ▾</button>
    <div class="dd-panel" id="f_stations"></div>
  </div>
  <label>築 <select id="f_age">
    <option value="">指定なし</option>
    <option value="5">5年以内</option>
    <option value="10">10年以内</option>
    <option value="15">15年以内</option>
    <option value="20">20年以内</option>
    <option value="25">25年以内</option>
    <option value="30">30年以内</option>
  </select></label>
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
建物名は SUUMO 掲載の見出し。建物名未登録の掲載は「路線 駅 N階建」
形式で表示され、リンク先が同一建物の別部屋になることがある。</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
let DATA, MAP, LAYER, GMAP, GMARKERS, IW;
let PROVIDER = null;
fetch("data.json").then(r => r.json()).then(d => {
  DATA = d;
  document.getElementById("meta").textContent =
    `生成 ${d.generated_at} / 母数 ${d.meta.rows.toLocaleString()} 件 / `
    + `モデル CV R2=${(d.meta.r2 ?? 0).toFixed(3)} MAE=${Math.round(d.meta.mae_yen ?? 0).toLocaleString()}円`;
  const freq = {};
  for (const r of d.rows) {
    const k = r.l || "";
    if (k) freq[k] = (freq[k] || 0) + 1;
  }
  const layouts = Object.keys(freq).sort((a, b) => freq[b] - freq[a]);
  document.getElementById("f_layouts").innerHTML = layouts.map(l =>
    `<label style="margin-right:6px"><input type="checkbox"
      class="f_lo" value="${l}">${l}</label>`).join("");
  const sfreq = {};
  for (const r of d.rows) {
    const k = r.st || "";
    if (k) sfreq[k] = (sfreq[k] || 0) + 1;
  }
  const stations = Object.keys(sfreq).sort((a, b) => sfreq[b] - sfreq[a]);
  document.getElementById("f_stations").innerHTML = stations.map(st =>
    `<label><input type="checkbox" class="f_st" value="${st}">${st}</label>`)
    .join("");
  wireDropdowns();
  render();
  initMap();
  // ドロップダウン: クリックで下に開き、外側クリックで閉じる。
  // ボタンには選択数を表示する
  function wireDropdowns() {
    for (const [btnId, panelId, label] of [
      ["dd_lo_btn", "f_layouts", "間取り"],
      ["dd_st_btn", "f_stations", "駅"]]) {
      const btn = document.getElementById(btnId);
      const dd = btn.parentElement;
      btn.onclick = (e) => {
        e.stopPropagation();
        const wasOpen = dd.classList.contains("open");
        for (const d of document.querySelectorAll(".dd.open"))
          d.classList.remove("open");
        if (!wasOpen) dd.classList.add("open");
      };
      dd.addEventListener("change", refreshDDLabels);
    }
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".dd"))
        for (const d of document.querySelectorAll(".dd.open"))
          d.classList.remove("open");
    });
    refreshDDLabels();
  }
  function refreshDDLabels() {
    const count = (cls) =>
      document.querySelectorAll(cls + ":checked").length;
    document.getElementById("dd_lo_btn").textContent =
      "間取り" + (count(".f_lo") ? ` (${count(".f_lo")})` : "") + " ▾";
    document.getElementById("dd_st_btn").textContent =
      "駅" + (count(".f_st") ? ` (${count(".f_st")})` : "") + " ▾";
  }
});
function __gmCb() {
  PROVIDER = "g";
  GMAP = new google.maps.Map(document.getElementById("map"),
    {center: {lat: 34.6815, lng: 135.4953}, zoom: 13,
     mapTypeControl: false, streetViewControl: false});
  GMARKERS = [];
  IW = new google.maps.InfoWindow();
  drawMap();
}
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
  // 間取り・駅: チェックが1つも無ければ全件
  const loSel = [...document.querySelectorAll(".f_lo:checked")]
    .map(x => x.value);
  const stSel = [...document.querySelectorAll(".f_st:checked")]
    .map(x => x.value);
  // 築年数上限 (空欄なら無制限)。築年数不明の行は上限設定時に除外
  const ageMax = document.getElementById("f_age").value;
  const age = ageMax === "" ? null : +ageMax;
  let rows = DATA.rows.filter(r =>
    r.tot <= tot && r.w != null && r.w <= walk
    && (!effOnly || r.eff != null)
    && (loSel.length === 0 || loSel.includes(r.l))
    && (stSel.length === 0 || stSel.includes(r.st))
    && (age === null || (r.y != null && r.y <= age))
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
  const tips = {
    "割安%": "公正価値(同じ駅・間取り・面積・築年の物件から予測した適正額)"
      + "より総額が安い割合。25%なら4分の1安い",
    総額: "毎月の支払い = 賃料 + 管理費",
    実質: "総額 + 毎月の固定費(水道・月額サポート) + 初期費用(礼金・仲介"
      + "手数料・火災保険・鍵交換等)と更新料を2年で割った月額。"
      + "初期費用取得済みの行のみ表示",
    "2年": "2年間で払う総額 (初期費用・敷金・更新料込み、フリーレント分控除)",
    面積: "専有面積 (m2)",
    築: "築年数",
    徒歩: "最寄り駅までの徒歩分数",
    "建物(リンク)": "クリックでSUUMOの物件ページを開く",
    設備: "SUUMO記載の設備一覧 (先頭120文字)",
  };
  const hs = ["割安%", "総額", "実質", "2年", "間取", "面積", "階", "築",
              "徒歩", "駅", "建物(リンク)", "設備"];
  thead.innerHTML = "<tr>" + hs.map(h =>
    `<th title="${tips[h] ?? ""}">${h}</th>`).join("") + "</tr>";
  const tb = document.getElementById("tbl").tBodies[0];
  const shown = displayed();
  tb.innerHTML = shown.map(r => {
    return `<tr><td class="disc">${r.disc ?? "-"}</td>`
      + `<td>${(r.tot / 10000).toFixed(1)}万</td>`
      + `<td>${r.eff ? (r.eff / 10000).toFixed(2) + "万" : "-"}</td>`
      + `<td>${r.t2 ? (r.t2 / 10000).toFixed(0) + "万" : "-"}</td>`
      + `<td>${r.l || "-"}</td><td>${r.a ?? "-"}</td><td>${r.f ?? "-"}</td>`
      + `<td>${r.y ?? "-"}</td><td>${r.w ?? "-"}</td><td>${r.st || "-"}</td>`
      + `<td class="url"><a href="${r.url}" target="_blank" rel="noopener">${r.n}</a></td>`
      + `<td>${r.eq}</td></tr>`;
  }).join("");
  if (shown.length < rows.length) {
    tb.insertAdjacentHTML("beforeend",
      `<tr><td colspan=13>… 先頭${shown.length}件のみ表示`
      + ` (条件に合うのは全${rows.length}件)。</td></tr>`);
  }
}
function initMap() {
  if (window.GKEY) {
    // Google Maps (普段使いの見た目)。キーはビルド時に注入。
    PROVIDER = "g-loading";
    const sc = document.createElement("script");
    sc.src = "https://maps.googleapis.com/maps/api/js?key="
      + encodeURIComponent(window.GKEY)
      + "&callback=__gmCb&loading=async";
    sc.async = true;
    document.head.appendChild(sc);
    return;
  }
  PROVIDER = "osm";
  MAP = L.map("map").setView([34.6815, 135.4953], 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    {attribution: "© OpenStreetMap"}).addTo(MAP);
  LAYER = L.layerGroup().addTo(MAP);
  drawMap();
}

function discColor(t, light) {
  return `hsl(${210 - 210 * t}, 70%, ${light ? 55 : 42}%)`;
}
function markerHTML(r) {
  return `<div style="font-family:system-ui;font-size:13px">`
    + `<a href="${r.url}" target="_blank" rel="noopener"><b>${r.n}</b></a>`
    + `<br>割安 <b>${r.disc ?? "-"}%</b> `
    + `(公正${r.fair ? (r.fair / 10000).toFixed(1) + "万" : "-"} /`
    + ` 実${(r.tot / 10000).toFixed(1)}万)`
    + `<br>${r.l} ${r.a}m2 ${r.st} 歩${r.w}分</div>`;
}

function drawMap() {
  const rows = displayed().filter(r => r.lat != null && r.lon != null);
  const discs = rows.map(r => r.disc ?? 0).sort((a, b) => a - b);
  const dmax = discs.length ? discs[Math.floor(discs.length * 0.95)] : 0;
  const scale = v => Math.max(0, Math.min(1, v / Math.max(dmax, 1)));
  if (PROVIDER === "g") {
    // Google Maps: 割安度で半径と色が変わる円 (メートル指定で
    // ズームに応じてスケールする)
    for (const m of GMARKERS) m.setMap(null);
    GMARKERS = [];
    for (const r of rows) {
      const t = scale(r.disc ?? 0);
      const c = new google.maps.Circle({
        center: {lat: r.lat, lng: r.lon},
        radius: 60 + 140 * t,
        strokeColor: discColor(t, false),
        fillColor: discColor(t, true), fillOpacity: .8, map: GMAP,
        clickable: true});
      c.addListener("click", () => {
        IW.setContent(markerHTML(r));
        IW.open({anchor: c, map: GMAP});
      });
      GMARKERS.push(c);
    }
    return;
  }
  if (PROVIDER !== "osm" || !LAYER) return;
  LAYER.clearLayers();
  for (const r of rows) {
    const t = scale(r.disc ?? 0);
    // 割安度が高いほど赤く・大きく (青→赤のグラデーション)
    L.circleMarker([r.lat, r.lon], {radius: 4 + 7 * t,
      color: discColor(t, false),
      fillColor: discColor(t, true), fillOpacity: .8,
      weight: 1})
      .bindPopup(markerHTML(r))
      .addTo(LAYER);
  }
}
document.getElementById("filters").addEventListener("change", () => {
  if (typeof refreshDDLabels === "function") refreshDDLabels();
  render();
  drawMap();
});
document.getElementById("f_q").addEventListener("input", () => {
  render();
  drawMap();
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
