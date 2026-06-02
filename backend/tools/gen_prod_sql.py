"""Generate prod MySQL migration SQL for configurator v2 / TEST GRP (trailer 51)."""
import sqlite3

DB = r'C:\Users\micge\Documents\Costing model\costing.db'
OUT = r'C:\Users\micge\Documents\Costing model\tools\prod_migration_configurator_v2.sql'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

c.execute('PRAGMA table_info(bill_of_materials)')
all_cols = [r[1] for r in c.fetchall()]


def qv(v):
    if v is None:
        return 'NULL'
    if isinstance(v, (int, float)):
        return str(v)
    safe = str(v).replace("'", "''")
    return f"'{safe}'"


lines = [
    '-- ============================================================',
    '-- PROD MySQL MIGRATION -- Configurator v2 for TEST GRP (id=51)',
    '-- Apply AFTER: git pull + touch restart.txt',
    '-- (app startup auto-adds any missing columns via ensure_columns)',
    '-- ============================================================',
    'SET foreign_key_checks = 0;',
    '',
    '-- 1. body_option_groups (ids 22-27)',
]

c.execute('SELECT id, name, sort_order, bom_section_id, parent_option_master_id FROM body_option_groups WHERE id>=22 ORDER BY id')
for g in c.fetchall():
    lines.append(
        f"INSERT INTO body_option_groups (id,name,sort_order,bom_section_id,parent_option_master_id) "
        f"VALUES ({g['id']},{qv(g['name'])},{g['sort_order']},{qv(g['bom_section_id'])},{qv(g['parent_option_master_id'])}) "
        f"ON DUPLICATE KEY UPDATE name=VALUES(name),bom_section_id=VALUES(bom_section_id),parent_option_master_id=VALUES(parent_option_master_id);"
    )

lines += ['', '-- 2. bom_sections (ids 39, 40)']
c.execute('SELECT id, name, sort_order, multiplier, body_option_master_id FROM bom_sections WHERE id>=39 ORDER BY id')
for s in c.fetchall():
    lines.append(
        f"INSERT INTO bom_sections (id,name,sort_order,multiplier,body_option_master_id) "
        f"VALUES ({s['id']},{qv(s['name'])},{s['sort_order']},{s['multiplier']},{qv(s['body_option_master_id'])}) "
        f"ON DUPLICATE KEY UPDATE name=VALUES(name),multiplier=VALUES(multiplier),body_option_master_id=VALUES(body_option_master_id);"
    )

lines += ['', '-- 3. bom_sections body_option_master_id (gate option ownership)']
c.execute('SELECT id, name, body_option_master_id FROM bom_sections WHERE body_option_master_id IS NOT NULL ORDER BY id')
for r in c.fetchall():
    lines.append(f"UPDATE bom_sections SET body_option_master_id={r['body_option_master_id']} WHERE id={r['id']};  -- {r['name']}")

lines += ['', '-- 4. configurator_v2 on TEST GRP']
lines.append('UPDATE trailer_types SET configurator_v2=1 WHERE id=51;')

lines += ['', '-- 5. BOM rows for trailer 51 -- wipe and re-insert']
lines.append('DELETE FROM bill_of_materials WHERE trailer_type_id=51;')
c.execute('SELECT * FROM bill_of_materials WHERE trailer_type_id=51 ORDER BY id')
col_list = ','.join(all_cols)
for row in c.fetchall():
    vals = ','.join([qv(row[col]) for col in all_cols])
    lines.append(f'INSERT INTO bill_of_materials ({col_list}) VALUES ({vals});')

lines += ['', 'SET foreign_key_checks = 1;', '-- END']

conn.close()

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print(f'Written {len(lines)} lines to {OUT}')
