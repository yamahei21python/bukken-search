# datafix 2026-10-26 cleanup（監査修正後の最終整備）

F1〜F10 と見送り解消を入れた後の DB 最終整備。Datafix ワークフロー（package に `datafix/20261026-cleanup` を指定）で適用する。

## 内容
1. `db.initialize_db`（repo 標準の初期化）: スキーマ補完、evidence / listing_snapshots の重複整理、カラム移行。死にカラム evidence.photo_url の物理 DROP はここで効く。
2. F7 外れ値駅の削除: unit の最寄り+30分超の駅行を削除する（修正後のパーサ/保存が書かない形への既存行の追随）。対象は実測2件（unit 4719 九条36分、unit 4722 朝潮橋40分）。
3. 陳腐化 listings の非活性化（last_seen 7日超、rebuild_db と同規則。実測0件）。
4. 検証: §8 バッテリー（integrity、異常値 0 件群、'None' 文字列 0）＋ D1/D3/F9/geocode のスポット値。全通過時のみ次へ進む（失敗時は非ゼロ終了し、ワークフローは commit しない）。
5. VACUUM。

## 対象外（意図的にやらないこと）
- listing の無い unit（630件）の削除: stations / evidence がぶら下がり、再掲載時に浴槽判定の集約材料になるため inert なまま残す。
- F5/F6 の建物・unit 統合: 日次 scrape の再保存で順次効く（作り直し専用ツールは repo に無い）。
- VACUUM の削減効果は現状ほぼゼロ（freelist 0）。整備の一環として実行だけする。
