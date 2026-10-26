# datafix 2026-10-26 F9（更新事務手数料カラム）

PR（F9）と対のデータ移行。`costs.renewal_admin_fee_yen` を既存 DB に追加し、詳細取得済み行の備考に残っている更新事務手数料を backfill する。

## 設計
- カラム追加は db.py の軽量マイグレーション（`_COSTS_COLUMNS`）と同一。次回 scrape の初期化でも冪等に追加されるため、本パッケージは「マージ直後に消費側（rank / cost_perf）が落ちないようにする即時適用」が目的。
- backfill の抽出規則はパーサ本体 `parse_suumo._labeled_yen` をそのまま使い、家賃×3 ガードもパーサと同一。ロジックの複製はしない。
- 対象は fetched=1 かつ note に「更新事務手数料」を含む行のみ。検証は「対象全行で保存値 == 備考からの再計算値」＋ integrity_check。失敗時は ROLLBACK。

## 実行前の実測（main @9aec7b7 の DB）
- 対象 35行、全行が解析可能。値: 11,000円×9、14,300円×6、16,500円×5、22,000円×8、27,500円×3、33,000円×1、11,990円×1（1.199万円表記）、他。

## 備考
- 一覧側（scraper.py）と migrate.py の costs INSERT は更新系の情報を持たないため変更なし（新カラムは NULL 既定）。
- 適用は Datafix ワークフロー（package に `datafix/20261026-f9` を指定）で行う。ワークフロー側に pyyaml 等の導入ステップを F9 の PR で追加済み（パーサ import 用）。
