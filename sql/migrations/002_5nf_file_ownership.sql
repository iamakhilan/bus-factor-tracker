-- One-time migration for existing installations.
-- Back up the database before running this migration.
-- Run: mysql -u root -p bus_factor_tracker < sql/migrations/002_5nf_file_ownership.sql
-- Do not run against a fresh database; schema_mysql.sql already contains the new design.

CREATE TABLE repo_module (
    module_id    INT AUTO_INCREMENT PRIMARY KEY,
    repo_id      INT NOT NULL,
    module_path  VARCHAR(255) NOT NULL,
    UNIQUE KEY uq_repo_module_path (repo_id, module_path),
    UNIQUE KEY uq_repo_module_pair (repo_id, module_id),
    CONSTRAINT fk_repo_module_repository
      FOREIGN KEY (repo_id) REFERENCES repository(repo_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE repository_file (
    file_id     BIGINT AUTO_INCREMENT PRIMARY KEY,
    repo_id     INT NOT NULL,
    module_id   INT NOT NULL,
    file_path   VARCHAR(512) NOT NULL,
    UNIQUE KEY uq_repo_file_path (repo_id, file_path),
    UNIQUE KEY uq_repo_file_pair (repo_id, file_id),
    KEY idx_repository_file_module (repo_id, module_id),
    CONSTRAINT fk_repository_file_module
      FOREIGN KEY (repo_id, module_id)
      REFERENCES repo_module(repo_id, module_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE file_contributor_activity (
    file_id        BIGINT NOT NULL,
    contributor_id INT NOT NULL,
    commit_count   INT NOT NULL DEFAULT 0,
    additions      INT NOT NULL DEFAULT 0,
    deletions      INT NOT NULL DEFAULT 0,
    sampled_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (file_id, contributor_id),
    CONSTRAINT fk_file_activity_file
      FOREIGN KEY (file_id) REFERENCES repository_file(file_id) ON DELETE CASCADE,
    CONSTRAINT fk_file_activity_contributor
      FOREIGN KEY (contributor_id) REFERENCES contributor(contributor_id) ON DELETE CASCADE
) ENGINE=InnoDB;

INSERT INTO repo_module (repo_id, module_path)
SELECT DISTINCT repo_id,
       CASE WHEN INSTR(file_path, '/') = 0
            THEN '(root files)'
            ELSE SUBSTRING_INDEX(file_path, '/', 1)
       END
FROM module_ownership;

INSERT INTO repository_file (repo_id, module_id, file_path)
SELECT mo.repo_id, rm.module_id, mo.file_path
FROM module_ownership mo
JOIN repo_module rm
  ON rm.repo_id = mo.repo_id
 AND rm.module_path = CASE WHEN INSTR(mo.file_path, '/') = 0
                           THEN '(root files)'
                           ELSE SUBSTRING_INDEX(mo.file_path, '/', 1)
                      END;

INSERT INTO file_contributor_activity
    (file_id, contributor_id, commit_count, additions, deletions, sampled_at)
SELECT rf.file_id, mo.contributor_id, mo.commit_count, mo.additions, mo.deletions, mo.sampled_at
FROM module_ownership mo
JOIN repository_file rf
  ON rf.repo_id = mo.repo_id AND rf.file_path = mo.file_path;

DROP TABLE module_ownership;

CREATE VIEW module_ownership AS
SELECT rf.repo_id, rf.file_path, fca.contributor_id,
       fca.commit_count, fca.additions, fca.deletions, fca.sampled_at
FROM repository_file rf
JOIN file_contributor_activity fca ON fca.file_id = rf.file_id;
