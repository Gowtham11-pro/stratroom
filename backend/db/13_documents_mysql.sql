-- MySQL tables for documents (replacing PG)

CREATE TABLE IF NOT EXISTS documents (
    id INT AUTO_INCREMENT PRIMARY KEY,
    org_id INT NOT NULL,
    user_id INT NOT NULL,
    filename VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    content_type VARCHAR(255) NOT NULL,
    file_size INT NOT NULL,
    extracted_text LONGTEXT,
    storage_path VARCHAR(512) NOT NULL,
    uploaded_by VARCHAR(255) DEFAULT '',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_docs_org (org_id),
    INDEX idx_docs_user (user_id),
    INDEX idx_docs_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS document_summaries (
    id INT AUTO_INCREMENT PRIMARY KEY,
    document_id INT NOT NULL,
    summary TEXT NOT NULL,
    provider VARCHAR(100) NOT NULL,
    model VARCHAR(200) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_docs_summary_doc (document_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
