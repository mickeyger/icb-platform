-- ============================================================
-- PROD MySQL MIGRATION -- configurator_draft_snapshots
-- Point-in-time backups of the Settings-page Explorer config draft per body
-- type. Distinct from configurator_snapshots (which captures BOM schema
-- state for the Configurator Preview page).
--
-- Apply AFTER: git pull + touch restart.txt
-- (Per feedback_prod_new_tables_manual: create_all does not reliably
--  add NEW tables on a Passenger restart — run this in cPanel Terminal
--  or phpMyAdmin before using the Snapshots feature on /admin/settings.)
-- ============================================================

CREATE TABLE IF NOT EXISTS configurator_draft_snapshots (
  id              INT(11) NOT NULL AUTO_INCREMENT,
  trailer_type_id INT(11) NOT NULL,
  label           VARCHAR(255) NOT NULL,
  payload         LONGTEXT NOT NULL,
  created_at      DATETIME NOT NULL,
  created_by      VARCHAR(100) DEFAULT NULL,
  PRIMARY KEY (id),
  KEY ix_cfg_draft_snap_trailer (trailer_type_id),
  CONSTRAINT fk_cfg_draft_snap_trailer
    FOREIGN KEY (trailer_type_id) REFERENCES trailer_types (id)
    ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
