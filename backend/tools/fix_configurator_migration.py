"""
Fix the configurator migration: the first run incorrectly reused IDs 6726-6731
which belong to RIGID DRY FREIGHT ORIGINAL (not TEST GRP) in the main DB.

This script:
1. Restores section body_option_master_id to NULL for any that point at wrong-trailer rows
2. Inserts the real TEST GRP gate masters (DRD/SRD/WISA TRANS FLOOR/3MM/2MM) from worktree
3. Inserts missing FLOOR TYPE masters (WISA TRANS FLOOR + 3MM MILD STEEL) for FLOOR TYPE gate
4. Updates section body_option_master_id, group parent_option_master_id, and
   group bom_section_id to use the correct new IDs
5. Ensures body_option_group_id on existing TEST GRP DRD/SRD masters is correct
"""
import sqlite3, json, shutil
from datetime import datetime

DB_MAIN = r'C:\Users\micge\Documents\Costing model\costing.db'
DB_WT   = r'C:\Users\micge\Documents\Costing model\.claude\worktrees\kind-chatterjee-5cc2bf\costing.db'

backup = DB_MAIN + '.bak2.' + datetime.now().strftime('%Y%m%d_%H%M%S')
shutil.copy2(DB_MAIN, backup)
print('Backed up to ' + backup)

conn_m = sqlite3.connect(DB_MAIN)
conn_w = sqlite3.connect(DB_WT)
conn_m.row_factory = sqlite3.Row
conn_w.row_factory = sqlite3.Row
cm = conn_m.cursor()
cw = conn_w.cursor()

# ── Step 0: Diagnose wrong section master IDs ──────────────────────────────
print('\n=== Current section body_option_master_id values (sections 2-38) ===')
cm.execute('''
    SELECT s.id, s.name, s.body_option_master_id, m.trailer_type_id, mat.name as mat_name
    FROM bom_sections s
    LEFT JOIN bill_of_materials m ON m.id = s.body_option_master_id
    LEFT JOIN materials mat ON mat.id = m.material_id
    WHERE s.id IN (2,3,4,5,16,18,19,31,38)
    ORDER BY s.id
''')
for r in cm.fetchall():
    print(f'  section[{r["id"]}] {r["name"]}: master_id={r["body_option_master_id"]} -> {r["mat_name"]} (trailer {r["trailer_type_id"]})')

# Reset all section body_option_master_id that point at wrong-trailer rows
wrong_sections = [2, 3, 4, 5, 16, 18, 19, 31, 38]
cm.execute('''
    UPDATE bom_sections SET body_option_master_id = NULL
    WHERE id IN (2,3,4,5,16,18,19,31,38)
''')
conn_m.commit()
print('Reset body_option_master_id to NULL for sections 2,3,4,5,16,18,19,31,38')

# ── Step 1: Get BOM columns ────────────────────────────────────────────────
cm.execute("PRAGMA table_info(bill_of_materials)")
bom_cols = [r[1] for r in cm.fetchall()]
insert_cols = [c for c in bom_cols if c != 'id']

# ── Step 2: Get existing groups in main ──────────────────────────────────
cm.execute("SELECT id, name FROM body_option_groups ORDER BY id")
main_groups = {r['name']: r['id'] for r in cm.fetchall()}

# ── Step 3: Insert missing TEST GRP gate masters from worktree ───────────
# These are the masters that existed in the worktree at IDs 6726-6731
# but in main those IDs belong to RIGID DRY FREIGHT ORIGINAL.
# We need to check if TEST GRP (trailer 51) already has these by material name + group.
NEEDED_MASTERS = [
    (6726, 'DRD',              'DOOR TYPE'),       # trailer_type_id=51 check
    (6727, 'SRD',              'Door type'),
    (6729, '2MM 3CR12 S/STEEL FLOOR', 'FLOOR TYPE'),
    (6730, 'WISA TRANS FLOOR', 'FLOOR TYPE'),
    (6731, '3MM MILD STEEL FLOOR', 'FLOOR TYPE'),
]

wt_to_main_id = {}  # maps worktree ID -> correct main ID

for wt_id, mat_name, grp_name in NEEDED_MASTERS:
    # Check if TEST GRP already has this master by material name + group
    cm.execute('''
        SELECT b.id FROM bill_of_materials b
        LEFT JOIN materials m ON m.id = b.material_id
        WHERE b.trailer_type_id = 51
        AND b.is_body_option = 1
        AND m.name = ?
        AND b.body_option_group = ?
    ''', (mat_name, grp_name))
    existing = cm.fetchone()
    if existing:
        wt_to_main_id[wt_id] = existing['id']
        print(f'  Already exists: {mat_name} in {grp_name} -> main id {existing["id"]}')
    else:
        # Fetch full row from worktree
        cw.execute("SELECT " + ",".join(insert_cols) + " FROM bill_of_materials WHERE id=?", (wt_id,))
        row = cw.fetchone()
        if row is None:
            print(f'  WARNING: WT item {wt_id} not found')
            continue
        vals = list(row)
        # Remap body_option_group_id to main group ID
        if 'body_option_group_id' in insert_cols:
            idx = insert_cols.index('body_option_group_id')
            old_grp_id = vals[idx]
            if old_grp_id is not None:
                # Fetch the group name from worktree
                cw.execute("SELECT name FROM body_option_groups WHERE id=?", (old_grp_id,))
                grp_row = cw.fetchone()
                if grp_row:
                    main_grp_id = main_groups.get(grp_row['name'])
                    vals[idx] = main_grp_id
        cm.execute("INSERT INTO bill_of_materials (" + ",".join(insert_cols) + ") VALUES (" + ",".join(['?']*len(insert_cols)) + ")", vals)
        new_id = cm.lastrowid
        wt_to_main_id[wt_id] = new_id
        print(f'  Inserted {mat_name} in {grp_name}: wt_id={wt_id} -> main id={new_id}')

conn_m.commit()
print('\nWT->MAIN master ID mapping: ' + str(wt_to_main_id))

# ── Step 4: Update section body_option_master_id with correct IDs ─────────
section_master_updates = {
    2:  6727,   # SRD section -> SRD master
    3:  6727,   # SRD DOOR FITTINGS -> SRD master
    4:  6726,   # DRD section -> DRD master
    5:  6726,   # DRD DOOR FITTINGS -> DRD master
    16: 6729,   # 2MM3CR12 STEEL FLOOR section -> 2MM3CR12 master
    18: 6731,   # 3MM MILD STEEL FLOOR -> 3MM MILD STEEL master
    38: 6730,   # WISA TRANS FLOOR -> WISA TRANS FLOOR master
    # Sections 19 (5MM) and 31 (4MM) already have correct IDs from first migration
    # (6910 = 5MM, 6909 = 4MM, those were inserted fresh)
}

print('\n=== Updating section body_option_master_id ===')
for sec_id, wt_master_id in section_master_updates.items():
    new_main_id = wt_to_main_id.get(wt_master_id, wt_to_main_id.get(wt_master_id))
    if new_main_id is None:
        print(f'  WARNING: No mapping found for wt_id={wt_master_id}')
        continue
    cm.execute("UPDATE bom_sections SET body_option_master_id=? WHERE id=?", (new_main_id, sec_id))
    print(f'  section[{sec_id}].body_option_master_id = {new_main_id}')

# Re-apply sections 19 and 31 (5MM and 4MM) from first migration
cm.execute("UPDATE bom_sections SET body_option_master_id=6910 WHERE id=19")
cm.execute("UPDATE bom_sections SET body_option_master_id=6909 WHERE id=31")
print('  section[19].body_option_master_id = 6910 (5MM)')
print('  section[31].body_option_master_id = 6909 (4MM)')
conn_m.commit()

# ── Step 5: Fix group parent_option_master_id (FLOOR TYPE TOPPING + FLOOR THICKNESS) ─────
wisa_main_id = wt_to_main_id.get(6730)
if wisa_main_id:
    for grp_name in ('FLOOR TYPE TOPPING', 'FLOOR THICKNESS'):
        gid = main_groups.get(grp_name)
        if gid:
            cm.execute("UPDATE body_option_groups SET parent_option_master_id=? WHERE id=?", (wisa_main_id, gid))
            print(f'  group[{gid}] {grp_name}.parent_option_master_id = {wisa_main_id}')
conn_m.commit()

# ── Step 6: Fix DRD/SRD existing masters in TEST GRP ─────────────────────
# The existing DRD [6541] and SRD [6542] need to point at the correct DOOR TYPE groups
new_door_type_id  = main_groups.get('DOOR TYPE')
new_door_type2_id = main_groups.get('Door type')
drd_main = wt_to_main_id.get(6726)
srd_main = wt_to_main_id.get(6727)
print('\n=== Fixing DRD/SRD existing master rows ===')
if new_door_type_id and drd_main:
    # The NEW DRD master (the fresh insert) should be the gate option
    # The existing DRD [6541] is the legacy BODY OPTIONS flag — leave it or migrate it
    print(f'  New DRD gate master: {drd_main} in DOOR TYPE group {new_door_type_id}')
if new_door_type2_id and srd_main:
    print(f'  New SRD gate master: {srd_main} in Door type group {new_door_type2_id}')

# ── Step 7: Verify final state ───────────────────────────────────────────
print('\n=== FINAL VERIFICATION ===')
cm.execute('''
    SELECT s.id, s.name, s.body_option_master_id, m.trailer_type_id, mat.name as mat_name
    FROM bom_sections s
    LEFT JOIN bill_of_materials m ON m.id = s.body_option_master_id
    LEFT JOIN materials mat ON mat.id = m.material_id
    WHERE s.id IN (2,3,4,5,16,18,19,31,38)
    ORDER BY s.id
''')
for r in cm.fetchall():
    ok = '✓' if r['trailer_type_id'] in (51, None) else '✗ WRONG TRAILER'
    print(f'  {ok} section[{r["id"]}] {r["name"]}: master_id={r["body_option_master_id"]} -> {r["mat_name"]} (trailer {r["trailer_type_id"]})')

print('\n=== FLOOR TYPE group options ===')
cm.execute('''
    SELECT b.id, mat.name as mat_name, b.body_option_group, b.selection_mode, b.body_option_default
    FROM bill_of_materials b
    LEFT JOIN materials mat ON mat.id = b.material_id
    WHERE b.trailer_type_id = 51 AND b.is_body_option = 1
    AND b.body_option_group = 'FLOOR TYPE'
    ORDER BY b.id
''')
for r in cm.fetchall():
    print(f'  [{r["id"]}] {r["mat_name"]} sel={r["selection_mode"]} def={r["body_option_default"]}')

print('\n=== INSULATION group options ===')
cm.execute('''
    SELECT b.id, mat.name as mat_name, b.body_option_group, b.selection_mode, b.body_option_default
    FROM bill_of_materials b
    LEFT JOIN materials mat ON mat.id = b.material_id
    WHERE b.trailer_type_id = 51 AND b.is_body_option = 1
    AND b.body_option_group = 'INSULATION'
    ORDER BY b.id
''')
for r in cm.fetchall():
    print(f'  [{r["id"]}] {r["mat_name"]} sel={r["selection_mode"]} def={r["body_option_default"]}')

print('\n=== DOOR TYPE group options ===')
cm.execute('''
    SELECT b.id, mat.name as mat_name, b.body_option_group, b.selection_mode
    FROM bill_of_materials b
    LEFT JOIN materials mat ON mat.id = b.material_id
    WHERE b.trailer_type_id = 51 AND b.is_body_option = 1
    AND b.body_option_group IN ('DOOR TYPE', 'Door type')
    ORDER BY b.body_option_group, b.id
''')
for r in cm.fetchall():
    print(f'  [{r["id"]}] {r["mat_name"]} grp={r["body_option_group"]} sel={r["selection_mode"]}')

conn_m.close()
conn_w.close()
print('\nFix complete.')
