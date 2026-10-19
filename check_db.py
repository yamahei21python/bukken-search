import sqlite3
c = sqlite3.connect('bukken.db')
print('--- table counts ---')
ts = ['buildings','units','listings','stations','costs','amenities','evidence',
      'viewings','favorites','contacts','notifications']
for t in ts:
    try:
        n = c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    except Exception as e:
        n = f'ERR: {e}'
    print(f'{t}: {n}')

print('--- costs ---')
print('total', c.execute('SELECT COUNT(*) FROM costs').fetchone()[0])
print('fetched=1', c.execute('SELECT COUNT(*) FROM costs WHERE fetched=1').fetchone()[0])
print('fetched=0', c.execute('SELECT COUNT(*) FROM costs WHERE fetched=0').fetchone()[0])
print('agency>0', c.execute('SELECT COUNT(*) FROM costs WHERE agency_yen>0').fetchone()[0])
print('km=deposit dup sample:')
for r in c.execute('SELECT key_money_yen,deposit_yen FROM costs WHERE key_money_yen>0 AND key_money_yen=deposit_yen LIMIT 3'):
    print('  key_money=',r[0],'deposit=',r[1])

print('--- costs linkage ---')
# how many costs point to a real listings.id vs unit id
print('costs.listing_id matches a listings.id:',
      c.execute('SELECT COUNT(*) FROM costs c JOIN listings l ON l.id=c.listing_id').fetchone()[0])
print('costs.listing_id matches a units.id:',
      c.execute('SELECT COUNT(*) FROM costs c JOIN units u ON u.id=c.listing_id').fetchone()[0])

print('--- stations ---')
print('units without station', c.execute('SELECT COUNT(*) FROM units u LEFT JOIN stations s ON s.unit_id=u.id WHERE s.id IS NULL').fetchone()[0])
print('station name empty', c.execute('SELECT COUNT(*) FROM stations WHERE name IS NULL OR name=\"\"').fetchone()[0])
print('dup stations per unit', c.execute('SELECT COUNT(*) FROM (SELECT unit_id FROM stations GROUP BY unit_id HAVING COUNT(*)>1)').fetchone()[0])
print('distinct station names:', c.execute('SELECT COUNT(DISTINCT name) FROM stations').fetchone()[0])
print('station names sample:')
for r in c.execute('SELECT DISTINCT name FROM stations ORDER BY name LIMIT 10'):
    print('  ', r[0])

print('--- listings link to units ---')
print('listings without unit_id:', c.execute('SELECT COUNT(*) FROM listings WHERE unit_id IS NULL').fetchone()[0])
print('--- properties ---')
print('properties rows', c.execute('SELECT COUNT(*) FROM properties').fetchone()[0])
print('properties has shikikin_yen col?', c.execute('PRAGMA table_info(properties)').fetchall())
pc = [i[1] for i in c.execute('PRAGMA table_info(properties)').fetchall()]
for col in ['station','shikikin_yen','reikin_yen']:
    print(f'  col {col}: present={col in pc}, sample=', c.execute(f'SELECT {col} FROM properties LIMIT 2').fetchall() if col in pc else 'N/A')
