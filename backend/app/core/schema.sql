CREATE TABLE IF NOT EXISTS "Users" (
    user_id     SERIAL PRIMARY KEY,
    username    VARCHAR(64)  NOT NULL UNIQUE,
    email       VARCHAR(254) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS "Experiments" (
    experiment_id SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES "Users"(user_id) ON DELETE CASCADE,
    title         VARCHAR(200) NOT NULL,
    description   TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_experiments_user_id ON "Experiments"(user_id);

CREATE TABLE IF NOT EXISTS "ExperimentRuns" (
    run_id        SERIAL PRIMARY KEY,
    experiment_id INTEGER NOT NULL REFERENCES "Experiments"(experiment_id) ON DELETE CASCADE,
    run_number    INTEGER NOT NULL,
    name          VARCHAR(200) NOT NULL,
    description   TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_run_number UNIQUE (experiment_id, run_number)
);
CREATE INDEX IF NOT EXISTS idx_runs_experiment_id ON "ExperimentRuns"(experiment_id);

CREATE TABLE IF NOT EXISTS "DataSeries" (
    series_id   SERIAL PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES "ExperimentRuns"(run_id) ON DELETE CASCADE,
    series_name VARCHAR(100) NOT NULL,
    unit_x      VARCHAR(32),
    unit_y      VARCHAR(32),
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_series_run_id ON "DataSeries"(run_id);

CREATE TABLE IF NOT EXISTS "DataPoints" (
    point_id          SERIAL PRIMARY KEY,
    series_id         INTEGER NOT NULL REFERENCES "DataSeries"(series_id) ON DELETE CASCADE,
    measurement_order INTEGER NOT NULL,
    x_value           DOUBLE PRECISION NOT NULL,
    y_value           DOUBLE PRECISION NOT NULL,
    x_uncertainty     DOUBLE PRECISION,
    y_uncertainty     DOUBLE PRECISION,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_point_order   UNIQUE (series_id, measurement_order),
    CONSTRAINT ck_x_unc_nonneg  CHECK (x_uncertainty IS NULL OR x_uncertainty >= 0),
    CONSTRAINT ck_y_unc_nonneg  CHECK (y_uncertainty IS NULL OR y_uncertainty >= 0)
);
CREATE INDEX IF NOT EXISTS idx_points_series_id ON "DataPoints"(series_id);

CREATE TABLE IF NOT EXISTS "Reports" (
    report_id  SERIAL PRIMARY KEY,
    run_id     INTEGER NOT NULL REFERENCES "ExperimentRuns"(run_id) ON DELETE CASCADE,
    title      VARCHAR(200) NOT NULL DEFAULT 'Untitled',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_reports_run_id ON "Reports"(run_id);

CREATE TABLE IF NOT EXISTS "Files" (
    file_id      SERIAL PRIMARY KEY,
    mime_type    VARCHAR(127) NOT NULL,
    storage_path TEXT         NOT NULL UNIQUE,
    size_bytes   BIGINT       NOT NULL,
    uploaded_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_size_nonneg CHECK (size_bytes >= 0)
);

CREATE TABLE IF NOT EXISTS "RunImages" (
    file_id INTEGER PRIMARY KEY REFERENCES "Files"(file_id) ON DELETE CASCADE,
    run_id  INTEGER NOT NULL    REFERENCES "ExperimentRuns"(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_run_images_run_id ON "RunImages"(run_id);

CREATE TABLE IF NOT EXISTS "ReportSourceFile" (
    report_id INTEGER PRIMARY KEY REFERENCES "Reports"(report_id) ON DELETE CASCADE,
    file_id   INTEGER NOT NULL UNIQUE REFERENCES "Files"(file_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "ReportPdfFile" (
    report_id INTEGER PRIMARY KEY REFERENCES "Reports"(report_id) ON DELETE CASCADE,
    file_id   INTEGER NOT NULL UNIQUE REFERENCES "Files"(file_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "ReportAttachments" (
    file_id   INTEGER PRIMARY KEY REFERENCES "Files"(file_id) ON DELETE CASCADE,
    report_id INTEGER NOT NULL    REFERENCES "Reports"(report_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_report_attachments_report_id ON "ReportAttachments"(report_id);

CREATE TABLE IF NOT EXISTS "SeriesPlotFile" (
    series_id INTEGER PRIMARY KEY REFERENCES "DataSeries"(series_id) ON DELETE CASCADE,
    file_id   INTEGER NOT NULL UNIQUE REFERENCES "Files"(file_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "FileDeletionQueue" (
    id           BIGSERIAL PRIMARY KEY,
    storage_path TEXT        NOT NULL,
    queued_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    retry_count  INTEGER     NOT NULL DEFAULT 0,
    last_error   TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_file_deletion_queue_pending
    ON "FileDeletionQueue" (storage_path) WHERE processed_at IS NULL;


CREATE OR REPLACE FUNCTION fn_set_updated_at()
RETURNS trigger AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    CREATE TRIGGER trg_updated_at_experiments
        BEFORE UPDATE ON "Experiments"
        FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_updated_at_experimentruns
        BEFORE UPDATE ON "ExperimentRuns"
        FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_updated_at_dataseries
        BEFORE UPDATE ON "DataSeries"
        FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_updated_at_reports
        BEFORE UPDATE ON "Reports"
        FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


CREATE OR REPLACE FUNCTION fn_assign_run_number()
RETURNS trigger AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(NEW.experiment_id);
    IF NEW.run_number IS NULL OR NEW.run_number = 0 THEN
        SELECT COALESCE(MAX(run_number), 0) + 1
          INTO NEW.run_number
          FROM "ExperimentRuns"
         WHERE experiment_id = NEW.experiment_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    CREATE TRIGGER trg_run_number
        BEFORE INSERT ON "ExperimentRuns"
        FOR EACH ROW EXECUTE FUNCTION fn_assign_run_number();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


CREATE OR REPLACE FUNCTION fn_cleanup_orphaned_file()
RETURNS trigger AS $$
BEGIN
    DELETE FROM "Files"
    WHERE file_id = OLD.file_id
      AND NOT EXISTS (SELECT 1 FROM "RunImages"         WHERE file_id = OLD.file_id)
      AND NOT EXISTS (SELECT 1 FROM "ReportSourceFile"  WHERE file_id = OLD.file_id)
      AND NOT EXISTS (SELECT 1 FROM "ReportPdfFile"     WHERE file_id = OLD.file_id)
      AND NOT EXISTS (SELECT 1 FROM "ReportAttachments" WHERE file_id = OLD.file_id)
      AND NOT EXISTS (SELECT 1 FROM "SeriesPlotFile"    WHERE file_id = OLD.file_id);
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    CREATE TRIGGER trg_cleanup_orphan_runimages
        AFTER DELETE ON "RunImages"
        FOR EACH ROW EXECUTE FUNCTION fn_cleanup_orphaned_file();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_cleanup_orphan_reportsourcefile
        AFTER DELETE ON "ReportSourceFile"
        FOR EACH ROW EXECUTE FUNCTION fn_cleanup_orphaned_file();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_cleanup_orphan_reportpdffile
        AFTER DELETE ON "ReportPdfFile"
        FOR EACH ROW EXECUTE FUNCTION fn_cleanup_orphaned_file();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_cleanup_orphan_reportattachments
        AFTER DELETE ON "ReportAttachments"
        FOR EACH ROW EXECUTE FUNCTION fn_cleanup_orphaned_file();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TRIGGER trg_cleanup_orphan_seriesplotfile
        AFTER DELETE ON "SeriesPlotFile"
        FOR EACH ROW EXECUTE FUNCTION fn_cleanup_orphaned_file();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


CREATE OR REPLACE FUNCTION fn_file_outbox()
RETURNS trigger AS $$
BEGIN
    INSERT INTO "FileDeletionQueue" (storage_path)
    VALUES (OLD.storage_path)
    ON CONFLICT DO NOTHING;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    CREATE TRIGGER trg_file_outbox
        AFTER DELETE ON "Files"
        FOR EACH ROW EXECUTE FUNCTION fn_file_outbox();
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
