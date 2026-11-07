# デプロイ手順 (Streamlit Community Cloud)

DB が repo 同梱 (`bukken.db`) のため、追加設定なしで無料の
Streamlit Community Cloud に置ける。スマホから割安ランキングと
マップが見られるようになる。

## 手順 (5分)

1. <https://share.streamlit.io> を開き、**GitHub でサインイン**
   (yamahei21python アカウント)
2. **Create app** → **Deploy a public app from GitHub**
3. 以下を入力して **Deploy**:
   - Repository: `yamahei21python/bukken-search`
   - Branch: `main`
   - Main file path: `app.py`
   - App URL (任意): 例 `bukken-search`
4. 初回起動は公正価値モデルの学習で 20〜60秒かかる
   (以後はフィルタ条件単位でキャッシュ)

## 更新の扱い

- `main` に push する (毎朝のスクレイプが bukken.db を自動コミット)
  と、クラウド側も自動で再デプロイされる
- app 画面右上のメニューから **Reboot** で手動再起動もできる

## 注意

- リポジトリは public であること (Community Cloud の要件)。
  個人利用の物件データで問題なければそのまま
- メモリ上限は約 1GB。DB は ~90MB と小さく問題ない
- 初期費用未取得行は「実質月額」が空欄になる (仕様)
- 値段が古い物件は `cost_perf` の既定フィルタ (last_seen 14日以内)
  で除外される

## ローカルで試す

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```
