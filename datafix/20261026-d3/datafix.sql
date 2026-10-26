-- bukken-search datafix 2026-10-26 D3 (guarantee_first tiny values) — single
-- source of truth. datafix.py executes the APPLY section of this file and
-- verifies with the CHECK section; the mutation logic lives only here.
--
-- Background: the listed costs.guarantee_first_yen values are exactly the
-- rent x 1% or x 2% — the MONTHLY guarantee rate misread as the initial fee
-- (old parser, pre-F3). Every target was confirmed against its live SUUMO
-- detail page on 2026-10-26; the evidence text is quoted in README.md.
--
-- Idempotency: every UPDATE is addressed by URL (never by internal row id)
-- and guarded by the known-bad current value, so a re-run changes 0 rows.
--
-- Targets (guarantee_first_yen old -> new):
--   SET  jnc_000110459926 (920)  630 -> 10000   (初回保証料:10000円)
--   SET  jnc_000110465360 (921)  630 -> 10000   (10,000円/入居時)
--   SET  jnc_000110323709 (1100) 1800 -> 33000  (初回:33000円)
--   SET  jnc_000110323707 (1101) 1800 -> 33000  (初回:33000円)
--   SET  jnc_000110434732 (3281) 646 -> 32300   (初回 総賃料50%)
--   SET+ jnc_000110434732 (3281) guarantee_renew_yen NULL -> 20000 (更新料[年])
--   SET  jnc_000110340402 (4183) 860 -> 43000   (初回 総賃料50%)
--   SET  jnc_000109222803 (8025) 625 -> 31250   (初回賃料総額50%)
--   SET  jnc_000109795770 (8080) 910 -> 35000   (保証料:35000円)
--   SET  jnc_000109222802 (8083) 515 -> 25750   (初回総賃料50%)
--   SET  jnc_000109480448 (8356) 800 -> 40000   (初回保証料:総賃料の50%)
--   NULL jnc_000110399007 (1971) 1520 -> NULL   (33,000円は初回契約事務手数料)
--   NULL jnc_000076636687 (1973) 1540 -> NULL   (同上)
--   NULL jnc_000110315502 (1980) 1600 -> NULL   (同上)
--   NULL jnc_000109086398 (8559) 1640 -> NULL   (33,000円は契約時事務手数料)
--   NULL jnc_000110445485 (2932) 510 -> NULL    (文面が一意に判読できない)
--   NULL jnc_000110005909 (8026) 625 -> NULL    (liveページに保証文面なし)
--   NULL jnc_000110711895 (8650) 480 -> NULL    (都度問合せ、額の記載なし)

BEGIN IMMEDIATE;
-- APPLY d3_920_gf
UPDATE costs SET guarantee_first_yen = 10000
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110459926/')
   AND guarantee_first_yen = 630;
-- APPLY d3_921_gf
UPDATE costs SET guarantee_first_yen = 10000
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110465360/')
   AND guarantee_first_yen = 630;
-- APPLY d3_1100_gf
UPDATE costs SET guarantee_first_yen = 33000
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110323709/')
   AND guarantee_first_yen = 1800;
-- APPLY d3_1101_gf
UPDATE costs SET guarantee_first_yen = 33000
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110323707/')
   AND guarantee_first_yen = 1800;
-- APPLY d3_3281_gf
UPDATE costs SET guarantee_first_yen = 32300
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110434732/')
   AND guarantee_first_yen = 646;
-- APPLY d3_3281_gr
UPDATE costs SET guarantee_renew_yen = 20000
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110434732/')
   AND guarantee_renew_yen IS NULL;
-- APPLY d3_4183_gf
UPDATE costs SET guarantee_first_yen = 43000
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110340402/')
   AND guarantee_first_yen = 860;
-- APPLY d3_8025_gf
UPDATE costs SET guarantee_first_yen = 31250
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000109222803/')
   AND guarantee_first_yen = 625;
-- APPLY d3_8080_gf
UPDATE costs SET guarantee_first_yen = 35000
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000109795770/')
   AND guarantee_first_yen = 910;
-- APPLY d3_8083_gf
UPDATE costs SET guarantee_first_yen = 25750
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000109222802/')
   AND guarantee_first_yen = 515;
-- APPLY d3_8356_gf
UPDATE costs SET guarantee_first_yen = 40000
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000109480448/')
   AND guarantee_first_yen = 800;
-- APPLY d3_1971_gf_null
UPDATE costs SET guarantee_first_yen = NULL
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110399007/')
   AND guarantee_first_yen = 1520;
-- APPLY d3_1973_gf_null
UPDATE costs SET guarantee_first_yen = NULL
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000076636687/')
   AND guarantee_first_yen = 1540;
-- APPLY d3_1980_gf_null
UPDATE costs SET guarantee_first_yen = NULL
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110315502/')
   AND guarantee_first_yen = 1600;
-- APPLY d3_8559_gf_null
UPDATE costs SET guarantee_first_yen = NULL
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000109086398/')
   AND guarantee_first_yen = 1640;
-- APPLY d3_2932_gf_null
UPDATE costs SET guarantee_first_yen = NULL
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110445485/')
   AND guarantee_first_yen = 510;
-- APPLY d3_8026_gf_null
UPDATE costs SET guarantee_first_yen = NULL
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110005909/')
   AND guarantee_first_yen = 625;
-- APPLY d3_8650_gf_null
UPDATE costs SET guarantee_first_yen = NULL
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000110711895/')
   AND guarantee_first_yen = 480;
COMMIT;

-- === CHECK section (run inside the transaction before COMMIT by datafix.py;
--     each CHECK names its expected single value; NULL means SQL NULL) ===
-- CHECK d3_920_gf expect: 10000
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110459926/';
-- CHECK d3_921_gf expect: 10000
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110465360/';
-- CHECK d3_1100_gf expect: 33000
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110323709/';
-- CHECK d3_1101_gf expect: 33000
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110323707/';
-- CHECK d3_3281_gf expect: 32300
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110434732/';
-- CHECK d3_3281_gr expect: 20000
SELECT c.guarantee_renew_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110434732/';
-- CHECK d3_4183_gf expect: 43000
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110340402/';
-- CHECK d3_8025_gf expect: 31250
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000109222803/';
-- CHECK d3_8080_gf expect: 35000
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000109795770/';
-- CHECK d3_8083_gf expect: 25750
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000109222802/';
-- CHECK d3_8356_gf expect: 40000
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000109480448/';
-- CHECK d3_1971_gf expect: NULL
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110399007/';
-- CHECK d3_1973_gf expect: NULL
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000076636687/';
-- CHECK d3_1980_gf expect: NULL
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110315502/';
-- CHECK d3_8559_gf expect: NULL
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000109086398/';
-- CHECK d3_2932_gf expect: NULL
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110445485/';
-- CHECK d3_8026_gf expect: NULL
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110005909/';
-- CHECK d3_8650_gf expect: NULL
SELECT c.guarantee_first_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110711895/';
-- CHECK d3_1971_gf_type expect: null
SELECT typeof(c.guarantee_first_yen) FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110399007/';
-- CHECK global_d3_candidates expect: 0
SELECT COUNT(*) FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE c.guarantee_first_yen IS NOT NULL AND c.guarantee_first_yen < 5000
   AND (c.guarantee_first_yen * 100 = l.rent_yen
        OR c.guarantee_first_yen * 50 = l.rent_yen);
-- CHECK global_guarantee_renew_huge expect: 0
SELECT COUNT(*) FROM costs WHERE guarantee_renew_yen >= 100000;
-- CHECK global_costs_text_gf expect: 0
SELECT COUNT(*) FROM costs WHERE typeof(guarantee_first_yen) = 'text';
