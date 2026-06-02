"""
Migrate TEST GRP configurator data from the worktree DB to the main DB.

What this script does:
1. Creates missing body_option_groups (Door type, DOOR TYPE, FLOOR TYPE, etc.)
2. Creates missing bom_sections (FLOOR THICKNESS, ALUMINIUM post-snapshot)
3. Inserts new BOM master rows (INSULATION flags, FLOOR TYPE options, etc.)
4. Maps old worktree IDs -> new main IDs for the new masters
5. Updates section body_option_master_id in main with new master IDs
6. Updates bom_conditions on TEST GRP items in main
7. Enables configurator_v2 for TEST GRP
8. Updates body_option_group_id on DRD/SRD masters (existing rows)
"""
import sqlite3, json, shutil, os
from datetime import datetime

DB_MAIN = r'C:\Users\micge\Documents\Costing model\costing.db'
DB_WT   = r'C:\Users\micge\Documents\Costing model\.claude\worktrees\kind-chatterjee-5cc2bf\costing.db'

# ── Backup ────────────────────────────────────────────────────────────────
backup = DB_MAIN + '.bak.' + datetime.now().strftime('%Y%m%d_%H%M%S')
shutil.copy2(DB_MAIN, backup)
print('Backed up main DB to ' + backup)

conn_m = sqlite3.connect(DB_MAIN)
conn_w = sqlite3.connect(DB_WT)
conn_m.row_factory = sqlite3.Row
conn_w.row_factory = sqlite3.Row
cm = conn_m.cursor()
cw = conn_w.cursor()

# ── Step 1: Get existing group IDs in main ──────────────────────────────
cm.execute("SELECT id, name FROM body_option_groups ORDER BY id")
main_groups = {r['name']: r['id'] for r in cm.fetchall()}
print('\nExisting groups in MAIN: ' + str(list(main_groups.keys())))

# ── Step 2: Copy new groups from worktree ─────────────────────────────
cw.execute("SELECT id, name, sort_order, bom_section_id, parent_option_master_id FROM body_option_groups WHERE id >= 22 ORDER BY id")
wt_new_groups = cw.fetchall()

wt_group_id_map = {}  # old wt id -> new main id
for g in wt_new_groups:
    if g['name'] in main_groups:
        wt_group_id_map[g['id']] = main_groups[g['name']]
        print("  Group '" + g['name'] + "' already exists in main (id=" + str(main_groups[g['name']]) + ")")
    else:
        cm.execute(
            "INSERT INTO body_option_groups (name, sort_order) VALUES (?, ?)",
            (g['name'], g['sort_order'])
        )
        new_id = cm.lastrowid
        wt_group_id_map[g['id']] = new_id
        main_groups[g['name']] = new_id
        print("  Created group '" + g['name'] + "' in MAIN with id=" + str(new_id) + " (was " + str(g['id']) + " in WT)")

conn_m.commit()

# ── Step 3: Copy new bom_sections from worktree ──────────────────────
cw.execute("SELECT id, name, sort_order, multiplier, body_option_master_id, archived_at FROM bom_sections WHERE id IN (39, 40)")
wt_new_sections = cw.fetchall()
cm.execute("SELECT id FROM bom_sections WHERE id IN (39, 40)")
existing_sec_ids = {r['id'] for r in cm.fetchall()}

wt_sec_id_map = {}  # old wt sec id -> new main id
for s in wt_new_sections:
    if s['id'] in existing_sec_ids:
        wt_sec_id_map[s['id']] = s['id']
        print("  Section [" + str(s['id']) + "] '" + s['name'] + "' already exists in main")
    else:
        cm.execute(
            "INSERT INTO bom_sections (name, sort_order, multiplier, archived_at) VALUES (?, ?, ?, ?)",
            (s['name'], s['sort_order'], s['multiplier'], s['archived_at'])
        )
        new_id = cm.lastrowid
        wt_sec_id_map[s['id']] = new_id
        print("  Created section '" + s['name'] + "' in MAIN with id=" + str(new_id) + " (was " + str(s['id']) + " in WT)")

conn_m.commit()

# ── Step 4: Get all BOM columns ─────────────────────────────────────
cm.execute("PRAGMA table_info(bill_of_materials)")
bom_cols = [r[1] for r in cm.fetchall()]

# ── Step 5: Copy new BOM master rows from worktree ───────────────────
new_wt_bom_ids = [6548, 6726, 6727, 6729, 6730, 6731, 6915, 6917, 6918, 6919,
                  6920, 6921, 6922, 6923, 6924, 6925, 6926, 6927, 6928, 6929,
                  6930, 6931, 6932]

cm.execute("SELECT id FROM bill_of_materials WHERE id IN (" + ",".join("?"*len(new_wt_bom_ids)) + ")", new_wt_bom_ids)
already_in_main = {r['id'] for r in cm.fetchall()}
print('\nAlready in MAIN: ' + str(sorted(already_in_main)))

to_insert = [bid for bid in new_wt_bom_ids if bid not in already_in_main]
print('To insert: ' + str(to_insert))

insert_cols = [c for c in bom_cols if c != 'id']

wt_bom_id_map = {}
for bid in already_in_main:
    wt_bom_id_map[bid] = bid

for wt_bid in to_insert:
    placeholders = ','.join(['?'] * len(insert_cols))
    cw.execute("SELECT " + ",".join(insert_cols) + " FROM bill_of_materials WHERE id=?", (wt_bid,))
    row = cw.fetchone()
    if row is None:
        print("  WARNING: WT item " + str(wt_bid) + " not found!")
        continue

    vals = list(row)
    # Remap body_option_group_id
    if 'body_option_group_id' in insert_cols:
        idx = insert_cols.index('body_option_group_id')
        if vals[idx] is not None:
            vals[idx] = wt_group_id_map.get(vals[idx], vals[idx])
    # Remap bom_section_id
    if 'bom_section_id' in insert_cols:
        idx = insert_cols.index('bom_section_id')
        if vals[idx] is not None:
            vals[idx] = wt_sec_id_map.get(vals[idx], vals[idx])

    cm.execute("INSERT INTO bill_of_materials (" + ",".join(insert_cols) + ") VALUES (" + placeholders + ")", vals)
    new_id = cm.lastrowid
    wt_bom_id_map[wt_bid] = new_id
    print("  Inserted WT item " + str(wt_bid) + " -> MAIN id " + str(new_id))

conn_m.commit()
print('\nBOM ID mapping: ' + str(wt_bom_id_map))

# ── Step 6: Update section body_option_master_id in main ─────────────
section_master_updates = {
    2:  6727,   # SRD
    3:  6727,   # SRD DOOR FITTINGS
    4:  6726,   # DRD
    5:  6726,   # DRD DOOR FITTINGS
    16: 6729,   # 2MM3CR12 STEEL FLOOR
    18: 6731,   # 3MM MILD STEEL FLOOR
    19: 6917,   # 5MM MILD STEEL FLOOR
    31: 6915,   # 4MM MILD STEEL FLOOR
    38: 6730,   # WISA TRANS FLOOR
}

print('\n=== Updating section body_option_master_id ===')
for sec_id, wt_master_id in section_master_updates.items():
    new_master_id = wt_bom_id_map.get(wt_master_id, wt_master_id)
    cm.execute("UPDATE bom_sections SET body_option_master_id=? WHERE id=?", (new_master_id, sec_id))
    print("  section[" + str(sec_id) + "].body_option_master_id = " + str(new_master_id))

conn_m.commit()

# ── Step 7: Update parent_option_master_id on groups ─────────────────
wisa_trans_floor_new_id = wt_bom_id_map.get(6730, 6730)
floor_thickness_sec_new_id = wt_sec_id_map.get(40, 40)
grp_parent_updates = {
    'FLOOR TYPE TOPPING': {'parent_option_master_id': wisa_trans_floor_new_id},
    'FLOOR THICKNESS': {
        'parent_option_master_id': wisa_trans_floor_new_id,
        'bom_section_id': floor_thickness_sec_new_id
    },
}

print('\n=== Updating group parent_option_master_id ===')
for grp_name, updates in grp_parent_updates.items():
    if grp_name in main_groups:
        gid = main_groups[grp_name]
        for col, val in updates.items():
            cm.execute("UPDATE body_option_groups SET " + col + "=? WHERE id=?", (val, gid))
            print("  group[" + str(gid) + "] '" + grp_name + "'." + col + " = " + str(val))

conn_m.commit()

# ── Step 8: Copy bom_conditions from worktree to main ────────────────
print('\n=== Copying bom_conditions ===')
cw.execute("""
    SELECT id, bom_conditions FROM bill_of_materials
    WHERE trailer_type_id = 51
    AND bom_conditions IS NOT NULL
    AND bom_conditions != ''
    AND bom_conditions != '[]'
""")
wt_conditions = cw.fetchall()

updated = 0
for r in wt_conditions:
    # Check if this ID exists in main DB
    cm.execute("SELECT id FROM bill_of_materials WHERE id=?", (r['id'],))
    if cm.fetchone():
        cm.execute("UPDATE bill_of_materials SET bom_conditions=? WHERE id=?",
                   (r['bom_conditions'], r['id']))
        updated += 1
        print("  [" + str(r['id']) + "] " + r['bom_conditions'][:80])
    else:
        print("  SKIP [" + str(r['id']) + "] not in MAIN (new row, already inserted with conditions)")

conn_m.commit()
print("Updated " + str(updated) + " items with bom_conditions")

# ── Step 9: Enable configurator_v2 for TEST GRP ──────────────────────
cm.execute("UPDATE trailer_types SET configurator_v2=1 WHERE id=51")
conn_m.commit()
print('\nEnabled configurator_v2 for TEST GRP (id=51)')

# ── Step 10: Update DRD/SRD masters group_id and selection_mode ──────
new_door_type_id = main_groups.get('DOOR TYPE')
new_door_type2_id = main_groups.get('Door type')
if new_door_type_id:
    cm.execute("UPDATE bill_of_materials SET body_option_group_id=?, selection_mode='single' WHERE id=6541 AND trailer_type_id=51", (new_door_type_id,))
    print("Updated DRD[6541] group_id=" + str(new_door_type_id) + " selection_mode=single")
if new_door_type2_id:
    cm.execute("UPDATE bill_of_materials SET body_option_group_id=?, selection_mode='single' WHERE id=6542 AND trailer_type_id=51", (new_door_type2_id,))
    print("Updated SRD[6542] group_id=" + str(new_door_type2_id) + " selection_mode=single")
conn_m.commit()

# ── Verification ─────────────────────────────────────────────────────
cm.execute("""SELECT COUNT(*) FROM bill_of_materials WHERE trailer_type_id=51
    AND bom_conditions IS NOT NULL AND bom_conditions != '' AND bom_conditions != '[]'""")
total_conds = cm.fetchone()[0]
cm.execute("SELECT configurator_v2 FROM trailer_types WHERE id=51")
v2 = cm.fetchone()[0]
cm.execute("SELECT COUNT(*) FROM bill_of_materials WHERE trailer_type_id=51 AND is_body_option=1")
masters = cm.fetchone()[0]
print('\n=== VERIFICATION ===')
print('TEST GRP bom_conditions count: ' + str(total_conds))
print('TEST GRP configurator_v2: ' + str(v2))
print('TEST GRP body option masters: ' + str(masters))

conn_m.close()
conn_w.close()
print('\nMigration complete.')
