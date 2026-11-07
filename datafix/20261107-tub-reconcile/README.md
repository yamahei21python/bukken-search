# 20261107-tub-reconcile

湯船判定の reconcile。unknown 24.1% (2,186/9,058) の解消。

## 調査で判明した原因

| 不整合 | 件数 | 内容 |
|---|---|---|
| 孤立 unit | 1,684 | listing を1つも持たない (unit 融合合致の取り残し)。うち unknown 1,126 |
| 判定失連 | 568 | `properties.has_bathtub=1` (湯船あり判定の記録) が有るのに `units.tub_status='unknown'` かつ evidence 無し |
| 真の曖昧 | 380 | evidence 有りで判定材料が本当に無い (設備文に湯船関連キーワード無し)。残す |

`has_bathtub=0` (湯船なし判定の記録) の evidence 失連は 0 件
(湯船なし側の取りこぼしは無い)。

## やること (models.reconcile_tub, 単体テスト済み)

1. 孤立 unit と付随行 (stations/amenities/evidence) を削除。unit を失った
   buildings も削除
2. evidence がある unit は aggregate_tub_status で再集約 (規約は evidence 寄り)
3. evidence 無し unit は properties から復元:
   - `has_bathtub=1` -> `likely_tub` (conf 0.6)
   - `has_bathtub=0` -> `no_bathtub_evidence` が有れば `confirmed_no_tub`
     (0.95)、無ければ `likely_no_tub` (0.6)
   - 複数仲介で割れる場合は湯船側勝ち
   - `method='reconcile'` の evidence 行を残し来歴と冪等性を保証

## 期待される効果

unknown 2,186件 -> 約500件 (24.1% -> 約6%)。rank の湯船スコア、
app の湯船フィルタ、コスパ回帰の has_bathtub 特徴が正しく効くように
なる。idempotent なので再実行は 0 件変更。
