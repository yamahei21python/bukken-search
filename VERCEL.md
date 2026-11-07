# 静的サイトの公開 (Vercel / GitHub Pages)

## 仕組み

```
毎朝の Scrape workflow (Actions)
  └─ build_site.py が site/index.html + data.json を生成
     └─ gh-pages ブランチへ force push (main は太らない)
        └─ Vercel / GitHub Pages が自動デプロイ
```

`site/` は main にコミットされない (1日 5.9MB ずつ増えるため)。
gh-pages ブランチだけが常に最新の2ファイルを持つ。

## Vercel で公開する (手順 2分)

1. <https://vercel.com> にサインイン (sara-vercel と同じアカウント)
2. **Add New... → Project** → `bukken-search` リポジトリを **Import**
3. 設定は以下のみ変更して **Deploy**:
   - Framework Preset: **Other**
   - **Production Branch: `gh-pages`** (デフォルトの main から変更)
   - Build Command / Output Directory: 空のまま
4. `https://<project>.vercel.app` で公開される

以後、毎朝のスクレイプが gh-pages を更新すると Vercel が自動で
再デプロイする。手動再デプロイは Vercel ダッシュボードから。

## 代替: GitHub Pages (Vercel 不要の場合)

Settings → Pages → Source: **Deploy from a branch** →
Branch: `gh-pages` / root → Save。
URL は `https://yamahei21python.github.io/bukken-search/`。

## 注意

- リポジトリが public のためサイトも公開になる (物件データは
  SUUMO の公開情報なので問題ないはず。気になるなら Vercel の
  Password Protection か GitHub Pages は private repo 不可に注意)
- マップタイル (OpenStreetMap) と Leaflet は CDN から読む
- data.json は約 6MB。初回読み込み後はブラウザキャッシュで高速

## 任意: マップを Google マップにする

Leaflet (OpenStreetMap) のままでも動くが、普段使いの見た目にしたい場合は
Google Maps JavaScript API が使える (キー必須・無料枠で十分)。

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクト作成
2. 「Maps JavaScript API」を有効化
3. 認証情報 → API キーを作成し、**HTTP リファラー制限**を設定
   (`https://<あなたのプロジェクト>.vercel.app/*` と `http://localhost:8123/*`)
   静的サイトは HTML にキーが含まれるため、この制限が必須
4. リポジトリに登録: `gh secret set GOOGLE_MAPS_API_KEY`
5. 次のスクレイプ (または手動で Scrape workflow 実行) から
   Google マップで描画される。キーが無ければ自動で Leaflet にフォールバック
