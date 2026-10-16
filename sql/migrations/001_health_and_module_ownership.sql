-- Apply once to an existing Bus Factor Tracker database.
-- Fresh installations should use sql/schema_mysql.sql instead.
ALTER TABLE repository ADD COLUMN last_pushed_at DATETIME NULL;

CREATE TABLE module_ownership (
    repo_id        INT NOT NULL,
    file_path      VARCHAR(1024) NOT NULL,
    contributor_id INT NOT NULL,
    commit_count   INT NOT NULL DEFAULT 0,
    additions      INT NOT NULL DEFAULT 0,
    deletions      INT NOT NULL DEFAULT 0,
    sampled_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (repo_id, file_path(255), contributor_id),
    CONSTRAINT fk_module_ownership_repo FOREIGN KEY (repo_id)
        REFERENCES repository(repo_id) ON DELETE CASCADE,
    CONSTRAINT fk_module_ownership_contributor FOREIGN KEY (contributor_id)
        REFERENCES contributor(contributor_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE INDEX idx_module_ownership_repo ON module_ownership(repo_id);
