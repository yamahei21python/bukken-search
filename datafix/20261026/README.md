# datafix 2026-10-26（監査 D1/D2）

bukken.db に対するデータ修正一式。修正ロジックの単一の真実は `datafix.sql` で、`datafix.py` がそれを実行・検証する。

## 適用方法
- 自動: `.github/workflows/datafix-20261026.yml` が `datafix/20261026/APPLY` の push（または手動 dispatch）で起動し、`datafix.py` を実行して、検証が全て通った場合のみ bukken.db をコミットする。
- 手動: `python3 datafix/20261026/datafix.py bukken.db datafix/20261026/datafix.sql`

## 規律
- 行指定は全て URL 基準（内部 id で直指定しない）。各 UPDATE は既知の旧値でガードされ、再実行では 0 件（冪等）。
- トランザクション: BEGIN IMMEDIATE → APPLY（changes() を文ごとに記録）→ CHECK 16件 + integrity_check → 全通過時のみ COMMIT。検証失敗時は ROLLBACK して何も commit しない。

## 対象（URL / 旧値 → 新値、根拠は live ページ確認）
- D1 https://suumo.jp/chintai/jnc_000110356595/ : properties.shikikin_yen 4,356,000,000 → NULL（listings / costs の同 URL 行は元々 NULL で、CHECK で検証のみ）
- D2 jnc_000107665732: costs.guarantee_renew_yen 150,000 → 10,000（エポス段階制の下段）
- D2 jnc_000107411633: 150,000 → NULL（現行ページに更新料の記載なし）
- D2 jnc_000109969016: 150,000 → 10,000（「1年更新:10,000円」）

## CHECK 節（16件）
- D1: 対象 URL の properties.shikikin_yen = NULL、その typeof = null、reikin_yen = NULL、listings.shikikin / reikin = NULL、costs.deposit_yen / key_money_yen = NULL。
- D2: 3 URL の期待値を個別検証（10,000 / NULL / 10,000）。
- 全体: properties の家賃×12 超（敷金・礼金）= 0、properties の text 型金額 = 0、listings の 'None' 文字列 = 0、costs の text 型金額 = 0、guarantee_renew_yen = 150,000 は 0。型混入は倍率チェックとは別クエリで検出する。
