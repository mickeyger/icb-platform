"""
Generate prod MySQL migration for trailer 51 WITHOUT explicit BOM row IDs.
Uses auto-increment and re-resolves FK references (body_option_master_id,
parent_option_master_id) via material-name lookups after insert.

material_id is also resolved by name so local SQLite IDs never appear in the SQL —
production MySQL material IDs may differ from local.
"""
import sqlite3

DB  = r'C:\Users\micge\Documents\Costing model\costing.db'
OUT = r'C:\Users\micge\Documents\Costing model\tools\prod_migration_configurator_v2_noids.sql'

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()

# Pre-build a material_id -> name lookup for the subquery substitution
c.execute('SELECT id, name FROM materials')
MAT_NAME = {r['id']: r['name'] for r in c.fetchall()}

c.execute('PRAGMA table_info(bill_of_materials)')
all_cols = [r[1] for r in c.fetchall()]
insert_cols = [col for col in all_cols if col != 'id']


def qv(v):
    if v is None:
        return 'NULL'
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def material_id_expr(mat_id):
    """Return a SQL expression that resolves the material by name on the target DB."""
    name = MAT_NAME.get(mat_id)
    if name is None:
        return 'NULL  /* WARNING: material_id %s not found locally */' % mat_id
    safe = name.replace("'", "''")
    return f"(SELECT MIN(id) FROM materials WHERE name='{safe}')"


lines = [
    '-- ============================================================',
    '-- PROD MySQL MIGRATION v2 (no explicit BOM IDs)',
    '-- Safe when prod IDs 6541-6930 are taken by other trailers.',
    '-- Apply AFTER: file upload + restart.txt touch.',
    '-- ============================================================',
    'SET foreign_key_checks = 0;',
    '',
    '-- 0. Ensure new columns exist (safe to re-run)',
    'ALTER TABLE body_option_groups   ADD COLUMN IF NOT EXISTS parent_option_master_id INTEGER;',
    'ALTER TABLE bom_sections         ADD COLUMN IF NOT EXISTS body_option_master_id   INTEGER;',
    'ALTER TABLE bom_sections         ADD COLUMN IF NOT EXISTS archived_at             TIMESTAMP NULL;',
    'ALTER TABLE trailer_types        ADD COLUMN IF NOT EXISTS configurator_v2         BOOLEAN NOT NULL DEFAULT 0;',
    "ALTER TABLE bill_of_materials    ADD COLUMN IF NOT EXISTS selection_mode          VARCHAR(16) NOT NULL DEFAULT 'always';",
    'ALTER TABLE bill_of_materials    ADD COLUMN IF NOT EXISTS selection_group         VARCHAR(100);',
    'ALTER TABLE bill_of_materials    ADD COLUMN IF NOT EXISTS bom_conditions          TEXT;',
    '',
    '-- 1. body_option_groups (upsert by id)',
]

c.execute('SELECT id, name, sort_order FROM body_option_groups WHERE id>=22 ORDER BY id')
for g in c.fetchall():
    lines.append(
        f"INSERT INTO body_option_groups (id,name,sort_order) "
        f"VALUES ({g['id']},{qv(g['name'])},{g['sort_order']}) "
        f"ON DUPLICATE KEY UPDATE name=VALUES(name);"
    )
# parent_option_master_id wired later after BOM rows are inserted

lines += ['', '-- 2. bom_sections (ids 39, 40 — these are metadata rows, safe to upsert)']
c.execute('SELECT id, name, sort_order, multiplier FROM bom_sections WHERE id>=39 ORDER BY id')
for s in c.fetchall():
    lines.append(
        f"INSERT INTO bom_sections (id,name,sort_order,multiplier) "
        f"VALUES ({s['id']},{qv(s['name'])},{s['sort_order']},{s['multiplier']}) "
        f"ON DUPLICATE KEY UPDATE name=VALUES(name);"
    )

lines += ['', '-- 3. configurator_v2']
lines.append('UPDATE trailer_types SET configurator_v2=1 WHERE id=51;')

lines += [
    '',
    '-- 4. Wipe existing trailer 51 BOM rows',
    'DELETE FROM bill_of_materials WHERE trailer_type_id=51;',
    '',
    '-- 5. Re-insert without explicit IDs (MySQL assigns new ones)',
]

col_list = ','.join(insert_cols)
c.execute('SELECT * FROM bill_of_materials WHERE trailer_type_id=51 ORDER BY id')
rows = c.fetchall()
for row in rows:
    vals_parts = []
    for col in insert_cols:
        if col == 'material_id' and row[col] is not None:
            vals_parts.append(material_id_expr(row[col]))
        else:
            vals_parts.append(qv(row[col]))
    vals = ','.join(vals_parts)
    lines.append(f'INSERT INTO bill_of_materials ({col_list}) VALUES ({vals});')

# Now resolve FK references using material name lookups.
# We need to know which material names correspond to the gate option masters
# so we can look them up after insert.

# Get the local master rows to know material names
c.execute('''
    SELECT b.id, mat.name as mat_name, b.body_option_group, b.selection_mode
    FROM bill_of_materials b
    JOIN materials mat ON mat.id = b.material_id
    WHERE b.trailer_type_id=51 AND b.is_body_option=1
    ORDER BY b.id
''')
masters = c.fetchall()

# Map: local_id -> mat_name for gate option masters (selection_mode=single in FLOOR TYPE / door groups)
gate_masters = [(m['id'], m['mat_name'], m['body_option_group']) for m in masters
                if m['selection_mode'] == 'single']

lines += [
    '',
    '-- 6. Re-wire bom_sections.body_option_master_id via material-name lookup',
    '--    (safe: only touches rows owned by trailer 51 masters)',
]

# For each section that had a body_option_master_id, look up the material name
c.execute('''
    SELECT s.id as sec_id, s.name as sec_name, mat.name as mat_name
    FROM bom_sections s
    JOIN bill_of_materials b ON b.id = s.body_option_master_id
    JOIN materials mat ON mat.id = b.material_id
    WHERE s.body_option_master_id IS NOT NULL
    ORDER BY s.id
''')
sec_masters = c.fetchall()
for sm in sec_masters:
    lines.append(
        f"UPDATE bom_sections SET body_option_master_id = ("
        f"  SELECT MIN(b.id) FROM bill_of_materials b"
        f"  JOIN materials mat ON mat.id=b.material_id"
        f"  WHERE b.trailer_type_id=51 AND b.is_body_option=1 AND mat.name={qv(sm['mat_name'])}"
        f") WHERE id={sm['sec_id']};  -- {sm['sec_name']} -> {sm['mat_name']}"
    )

lines += [
    '',
    '-- 7. Re-wire body_option_groups.parent_option_master_id via material-name lookup',
]

c.execute('''
    SELECT g.id as grp_id, g.name as grp_name, mat.name as mat_name
    FROM body_option_groups g
    JOIN bill_of_materials b ON b.id = g.parent_option_master_id
    JOIN materials mat ON mat.id = b.material_id
    WHERE g.parent_option_master_id IS NOT NULL
    ORDER BY g.id
''')
grp_parents = c.fetchall()
for gp in grp_parents:
    lines.append(
        f"UPDATE body_option_groups SET parent_option_master_id = ("
        f"  SELECT MIN(b.id) FROM bill_of_materials b"
        f"  JOIN materials mat ON mat.id=b.material_id"
        f"  WHERE b.trailer_type_id=51 AND b.is_body_option=1 AND mat.name={qv(gp['mat_name'])}"
        f") WHERE id={gp['grp_id']};  -- {gp['grp_name']} -> {gp['mat_name']}"
    )

lines += [
    '',
    'SET foreign_key_checks = 1;',
    '-- END',
]

conn.close()

with open(OUT, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print(f'Written {len(lines)} lines to {OUT}')
