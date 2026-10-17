-- Report-alignment migration: burnout signals, historical risk alerts, and DB objects.
-- Apply once to an existing database AFTER migrations 001 and 002.
-- Back up the database before applying. Fresh installs should use schema_mysql.sql
-- plus this migration's equivalent objects (kept here for existing installations).

ALTER TABLE bus_factor_snapshot
  ADD COLUMN activity_change_pct FLOAT NULL,
  ADD COLUMN top_contributor_days_inactive INT NULL,
  ADD COLUMN days_since_last_release INT NULL;

CREATE TABLE risk_alert (
  alert_id BIGINT AUTO_INCREMENT PRIMARY KEY,
  repo_id INT NOT NULL,
  snapshot_id INT NOT NULL,
  previous_level ENUM('Critical','High','Medium','Healthy') NOT NULL,
  new_level ENUM('Critical','High','Medium','Healthy') NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_risk_alert_created_at (created_at),
  KEY idx_risk_alert_repo_created (repo_id, created_at),
  CONSTRAINT fk_risk_alert_repo FOREIGN KEY (repo_id)
    REFERENCES repository(repo_id) ON DELETE CASCADE,
  CONSTRAINT fk_risk_alert_snapshot FOREIGN KEY (snapshot_id)
    REFERENCES bus_factor_snapshot(snapshot_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE OR REPLACE VIEW v_repo_latest_snapshot AS
SELECT s.*
FROM bus_factor_snapshot s
JOIN (
  SELECT repo_id, MAX(snapshot_id) AS snapshot_id
  FROM bus_factor_snapshot
  GROUP BY repo_id
) latest ON latest.snapshot_id = s.snapshot_id;

DELIMITER $$
CREATE FUNCTION fn_risk_rank(p_level VARCHAR(10))
RETURNS INT DETERMINISTIC
BEGIN
  RETURN CASE p_level
    WHEN 'Healthy' THEN 1
    WHEN 'Medium' THEN 2
    WHEN 'High' THEN 3
    WHEN 'Critical' THEN 4
    ELSE 0
  END;
END$$

CREATE PROCEDURE sp_declining_repos(IN p_days INT)
BEGIN
  SELECT r.owner, r.name, latest.bus_factor AS current_bus_factor,
         older.bus_factor AS previous_bus_factor,
         latest.risk_level AS current_risk, older.risk_level AS previous_risk,
         latest.computed_at AS current_computed_at,
         older.computed_at AS previous_computed_at
  FROM v_repo_latest_snapshot latest
  JOIN repository r ON r.repo_id = latest.repo_id
  JOIN bus_factor_snapshot older
    ON older.snapshot_id = (
      SELECT candidate.snapshot_id
      FROM bus_factor_snapshot candidate
      WHERE candidate.repo_id = latest.repo_id
        AND candidate.computed_at <= latest.computed_at - INTERVAL p_days DAY
      ORDER BY candidate.computed_at DESC, candidate.snapshot_id DESC
      LIMIT 1
    )
  WHERE fn_risk_rank(latest.risk_level) > fn_risk_rank(older.risk_level)
     OR latest.bus_factor < older.bus_factor
  ORDER BY fn_risk_rank(latest.risk_level) DESC, latest.computed_at DESC;
END$$

CREATE TRIGGER trg_snapshot_risk_alert
AFTER INSERT ON bus_factor_snapshot
FOR EACH ROW
BEGIN
  DECLARE v_previous_level VARCHAR(10);
  SELECT s.risk_level INTO v_previous_level
  FROM bus_factor_snapshot s
  WHERE s.repo_id = NEW.repo_id AND s.snapshot_id <> NEW.snapshot_id
  ORDER BY s.computed_at DESC, s.snapshot_id DESC
  LIMIT 1;

  IF v_previous_level IS NOT NULL
     AND fn_risk_rank(NEW.risk_level) > fn_risk_rank(v_previous_level) THEN
    INSERT INTO risk_alert(repo_id, snapshot_id, previous_level, new_level)
    VALUES (NEW.repo_id, NEW.snapshot_id, v_previous_level, NEW.risk_level);
  END IF;
END$$
DELIMITER ;

-- The sync pipeline must populate the three new signal columns before these
-- values can be used for risk scoring; NULL intentionally means unavailable.
