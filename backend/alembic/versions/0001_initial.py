"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-04-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "Users",
        sa.Column("user_id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "Experiments",
        sa.Column("experiment_id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("Users.user_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "ExperimentRuns",
        sa.Column("run_id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.Integer,
            sa.ForeignKey("Experiments.experiment_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("run_number", sa.Integer, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("experiment_id", "run_number", name="uq_run_number"),
    )

    op.create_table(
        "DataSeries",
        sa.Column("series_id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer,
            sa.ForeignKey("ExperimentRuns.run_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("series_name", sa.String(100), nullable=False),
        sa.Column("unit_x", sa.String(32)),
        sa.Column("unit_y", sa.String(32)),
        sa.Column("description", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "DataPoints",
        sa.Column("point_id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column(
            "series_id",
            sa.Integer,
            sa.ForeignKey("DataSeries.series_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("measurement_order", sa.Integer, nullable=False),
        sa.Column("x_value", sa.Float, nullable=False),
        sa.Column("y_value", sa.Float, nullable=False),
        sa.Column("x_uncertainty", sa.Float),
        sa.Column("y_uncertainty", sa.Float),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("series_id", "measurement_order", name="uq_point_order"),
        sa.CheckConstraint("x_uncertainty IS NULL OR x_uncertainty >= 0", name="ck_x_unc_nonneg"),
        sa.CheckConstraint("y_uncertainty IS NULL OR y_uncertainty >= 0", name="ck_y_unc_nonneg"),
    )

    op.create_table(
        "Reports",
        sa.Column("report_id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer,
            sa.ForeignKey("ExperimentRuns.run_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("title", sa.String(200), nullable=False, server_default="Untitled"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "Files",
        sa.Column("file_id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False, unique=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("size_bytes >= 0", name="ck_size_nonneg"),
    )

    op.create_table(
        "RunImages",
        sa.Column(
            "file_id",
            sa.Integer,
            sa.ForeignKey("Files.file_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "run_id",
            sa.Integer,
            sa.ForeignKey("ExperimentRuns.run_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )

    op.create_table(
        "ReportSourceFile",
        sa.Column(
            "report_id",
            sa.Integer,
            sa.ForeignKey("Reports.report_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "file_id",
            sa.Integer,
            sa.ForeignKey("Files.file_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
    )

    op.create_table(
        "ReportPdfFile",
        sa.Column(
            "report_id",
            sa.Integer,
            sa.ForeignKey("Reports.report_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "file_id",
            sa.Integer,
            sa.ForeignKey("Files.file_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
    )

    op.create_table(
        "ReportAttachments",
        sa.Column(
            "file_id",
            sa.Integer,
            sa.ForeignKey("Files.file_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "report_id",
            sa.Integer,
            sa.ForeignKey("Reports.report_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
    )

    op.create_table(
        "SeriesPlotFile",
        sa.Column(
            "series_id",
            sa.Integer,
            sa.ForeignKey("DataSeries.series_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "file_id",
            sa.Integer,
            sa.ForeignKey("Files.file_id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
    )

    op.create_table(
        "FileDeletionQueue",
        sa.Column("id", sa.BigInteger, sa.Identity(always=False), primary_key=True),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_file_deletion_queue_pending '
        'ON "FileDeletionQueue" (storage_path) WHERE processed_at IS NULL'
    )

    # updated_at BEFORE UPDATE triggers
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_set_updated_at()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("Experiments", "ExperimentRuns", "DataSeries", "Reports"):
        op.execute(
            f'CREATE TRIGGER trg_updated_at_{table.lower()} '
            f'BEFORE UPDATE ON "{table}" FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at();'
        )

    # run_number auto-assignment
    op.execute(
        """
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
        """
    )
    op.execute(
        'CREATE TRIGGER trg_run_number BEFORE INSERT ON "ExperimentRuns" '
        'FOR EACH ROW EXECUTE FUNCTION fn_assign_run_number();'
    )

    # orphaned file cleanup
    op.execute(
        """
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
        """
    )
    for table in ("RunImages", "ReportSourceFile", "ReportPdfFile", "ReportAttachments", "SeriesPlotFile"):
        op.execute(
            f'CREATE TRIGGER trg_cleanup_orphan_{table.lower()} '
            f'AFTER DELETE ON "{table}" FOR EACH ROW EXECUTE FUNCTION fn_cleanup_orphaned_file();'
        )

    # File outbox -> FileDeletionQueue
    op.execute(
        """
        CREATE OR REPLACE FUNCTION fn_file_outbox()
        RETURNS trigger AS $$
        BEGIN
            INSERT INTO "FileDeletionQueue" (storage_path)
            VALUES (OLD.storage_path)
            ON CONFLICT DO NOTHING;
            RETURN OLD;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        'CREATE TRIGGER trg_file_outbox AFTER DELETE ON "Files" '
        'FOR EACH ROW EXECUTE FUNCTION fn_file_outbox();'
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER IF EXISTS trg_file_outbox ON "Files"')
    op.execute("DROP FUNCTION IF EXISTS fn_file_outbox()")
    for table in ("RunImages", "ReportSourceFile", "ReportPdfFile", "ReportAttachments", "SeriesPlotFile"):
        op.execute(f'DROP TRIGGER IF EXISTS trg_cleanup_orphan_{table.lower()} ON "{table}"')
    op.execute("DROP FUNCTION IF EXISTS fn_cleanup_orphaned_file()")
    op.execute('DROP TRIGGER IF EXISTS trg_run_number ON "ExperimentRuns"')
    op.execute("DROP FUNCTION IF EXISTS fn_assign_run_number()")
    for table in ("Experiments", "ExperimentRuns", "DataSeries", "Reports"):
        op.execute(f'DROP TRIGGER IF EXISTS trg_updated_at_{table.lower()} ON "{table}"')
    op.execute("DROP FUNCTION IF EXISTS fn_set_updated_at()")

    op.drop_table("FileDeletionQueue")
    op.drop_table("SeriesPlotFile")
    op.drop_table("ReportAttachments")
    op.drop_table("ReportPdfFile")
    op.drop_table("ReportSourceFile")
    op.drop_table("RunImages")
    op.drop_table("Files")
    op.drop_table("Reports")
    op.drop_table("DataPoints")
    op.drop_table("DataSeries")
    op.drop_table("ExperimentRuns")
    op.drop_table("Experiments")
    op.drop_table("Users")
