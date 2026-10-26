-- bukken-search datafix 2026-10-26 (audit D1/D2) — single source of truth.
-- datafix.py executes the APPLY section of this file and verifies with the
-- CHECK section; the mutation logic lives only here.
--
-- Idempotency: every UPDATE is addressed by URL (never by internal row id)
-- and guarded by the known-bad current value, so a re-run changes 0 rows.
--
-- Targets (old -> new):
--   D1 https://suumo.jp/chintai/jnc_000110356595/
--      properties.shikikin_yen 4356000000 -> NULL
--      (listings.shikikin/reikin and costs.deposit_yen/key_money_yen for the
--       same URL were already NULL; they are covered by CHECKs below)
--   D2 https://suumo.jp/chintai/jnc_000107665732/ costs.guarantee_renew_yen 150000 -> 10000
--   D2 https://suumo.jp/chintai/jnc_000107411633/ costs.guarantee_renew_yen 150000 -> NULL
--   D2 https://suumo.jp/chintai/jnc_000109969016/ costs.guarantee_renew_yen 150000 -> 10000

BEGIN IMMEDIATE;
-- APPLY d1_properties_shikikin
UPDATE properties SET shikikin_yen = NULL
 WHERE detail_url = 'https://suumo.jp/chintai/jnc_000110356595/'
   AND shikikin_yen = 4356000000;
-- APPLY d2_4317_guarantee_renew
UPDATE costs SET guarantee_renew_yen = 10000
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000107665732/')
   AND guarantee_renew_yen = 150000;
-- APPLY d2_4830_guarantee_renew
UPDATE costs SET guarantee_renew_yen = NULL
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000107411633/')
   AND guarantee_renew_yen = 150000;
-- APPLY d2_4833_guarantee_renew
UPDATE costs SET guarantee_renew_yen = 10000
 WHERE listing_id = (SELECT id FROM listings
                      WHERE url = 'https://suumo.jp/chintai/jnc_000109969016/')
   AND guarantee_renew_yen = 150000;
COMMIT;

-- === CHECK section (run inside the transaction before COMMIT by datafix.py;
--     each CHECK names its expected single value; NULL means SQL NULL) ===
-- CHECK d1_properties_shikikin expect: NULL
SELECT shikikin_yen FROM properties
 WHERE detail_url = 'https://suumo.jp/chintai/jnc_000110356595/';
-- CHECK d1_properties_shikikin_type expect: null
SELECT typeof(shikikin_yen) FROM properties
 WHERE detail_url = 'https://suumo.jp/chintai/jnc_000110356595/';
-- CHECK d1_properties_reikin expect: NULL
SELECT reikin_yen FROM properties
 WHERE detail_url = 'https://suumo.jp/chintai/jnc_000110356595/';
-- CHECK d1_listings_shikikin expect: NULL
SELECT shikikin FROM listings
 WHERE url = 'https://suumo.jp/chintai/jnc_000110356595/';
-- CHECK d1_listings_reikin expect: NULL
SELECT reikin FROM listings
 WHERE url = 'https://suumo.jp/chintai/jnc_000110356595/';
-- CHECK d1_costs_deposit expect: NULL
SELECT c.deposit_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110356595/';
-- CHECK d1_costs_key_money expect: NULL
SELECT c.key_money_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000110356595/';
-- CHECK d2_4317 expect: 10000
SELECT c.guarantee_renew_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000107665732/';
-- CHECK d2_4830 expect: NULL
SELECT c.guarantee_renew_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000107411633/';
-- CHECK d2_4833 expect: 10000
SELECT c.guarantee_renew_yen FROM costs c JOIN listings l ON l.id = c.listing_id
 WHERE l.url = 'https://suumo.jp/chintai/jnc_000109969016/';
-- CHECK global_properties_giant_shikikin expect: 0
SELECT COUNT(*) FROM properties
 WHERE rent_yen > 0 AND shikikin_yen > rent_yen * 12;
-- CHECK global_properties_giant_reikin expect: 0
SELECT COUNT(*) FROM properties
 WHERE rent_yen > 0 AND reikin_yen > rent_yen * 12;
-- CHECK global_properties_text_yen expect: 0
SELECT COUNT(*) FROM properties
 WHERE typeof(shikikin_yen) = 'text' OR typeof(reikin_yen) = 'text';
-- CHECK global_listings_none_strings expect: 0
SELECT COUNT(*) FROM listings WHERE shikikin = 'None' OR reikin = 'None';
-- CHECK global_costs_text_yen expect: 0
SELECT COUNT(*) FROM costs
 WHERE typeof(deposit_yen) = 'text' OR typeof(key_money_yen) = 'text'
    OR typeof(guarantee_renew_yen) = 'text';
-- CHECK global_guarantee_renew_150000 expect: 0
SELECT COUNT(*) FROM costs WHERE guarantee_renew_yen = 150000;
