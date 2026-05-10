from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "Users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    experiments: Mapped[list["Experiment"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Experiment(Base):
    __tablename__ = "Experiments"

    experiment_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("Users.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="experiments")
    runs: Mapped[list["ExperimentRun"]] = relationship(
        back_populates="experiment", cascade="all, delete-orphan"
    )


class ExperimentRun(Base):
    __tablename__ = "ExperimentRuns"
    __table_args__ = (
        UniqueConstraint("experiment_id", "run_number", name="uq_run_number"),
    )

    run_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(
        ForeignKey("Experiments.experiment_id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    experiment: Mapped[Experiment] = relationship(back_populates="runs")
    series: Mapped[list["DataSeries"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    reports: Mapped[list["Report"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    images: Mapped[list["RunImage"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class DataSeries(Base):
    __tablename__ = "DataSeries"

    series_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ExperimentRuns.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    series_name: Mapped[str] = mapped_column(String(100), nullable=False)
    unit_x: Mapped[str | None] = mapped_column(String(32))
    unit_y: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[ExperimentRun] = relationship(back_populates="series")
    points: Mapped[list["DataPoint"]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )
    plot: Mapped["SeriesPlotFile | None"] = relationship(
        back_populates="series", cascade="all, delete-orphan", uselist=False
    )


class DataPoint(Base):
    __tablename__ = "DataPoints"
    __table_args__ = (
        UniqueConstraint("series_id", "measurement_order", name="uq_point_order"),
        CheckConstraint("x_uncertainty IS NULL OR x_uncertainty >= 0", name="ck_x_unc_nonneg"),
        CheckConstraint("y_uncertainty IS NULL OR y_uncertainty >= 0", name="ck_y_unc_nonneg"),
    )

    point_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    series_id: Mapped[int] = mapped_column(
        ForeignKey("DataSeries.series_id", ondelete="CASCADE"), nullable=False, index=True
    )
    measurement_order: Mapped[int] = mapped_column(Integer, nullable=False)
    x_value: Mapped[float] = mapped_column(Float, nullable=False)
    y_value: Mapped[float] = mapped_column(Float, nullable=False)
    x_uncertainty: Mapped[float | None] = mapped_column(Float)
    y_uncertainty: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    series: Mapped[DataSeries] = relationship(back_populates="points")


class Report(Base):
    __tablename__ = "Reports"

    report_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ExperimentRuns.run_id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, server_default="Untitled")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[ExperimentRun] = relationship(back_populates="reports")
    source: Mapped["ReportSourceFile | None"] = relationship(
        back_populates="report", cascade="all, delete-orphan", uselist=False
    )
    pdf: Mapped["ReportPdfFile | None"] = relationship(
        back_populates="report", cascade="all, delete-orphan", uselist=False
    )
    attachments: Mapped[list["ReportAttachment"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )


class File(Base):
    __tablename__ = "Files"
    __table_args__ = (
        CheckConstraint("size_bytes >= 0", name="ck_size_nonneg"),
    )

    file_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RunImage(Base):
    __tablename__ = "RunImages"

    file_id: Mapped[int] = mapped_column(
        ForeignKey("Files.file_id", ondelete="CASCADE"), primary_key=True
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ExperimentRuns.run_id", ondelete="CASCADE"), nullable=False, index=True
    )

    run: Mapped[ExperimentRun] = relationship(back_populates="images")
    file: Mapped[File] = relationship()


class ReportSourceFile(Base):
    __tablename__ = "ReportSourceFile"

    report_id: Mapped[int] = mapped_column(
        ForeignKey("Reports.report_id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("Files.file_id", ondelete="CASCADE"), unique=True, nullable=False
    )

    report: Mapped[Report] = relationship(back_populates="source")
    file: Mapped[File] = relationship()


class ReportPdfFile(Base):
    __tablename__ = "ReportPdfFile"

    report_id: Mapped[int] = mapped_column(
        ForeignKey("Reports.report_id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("Files.file_id", ondelete="CASCADE"), unique=True, nullable=False
    )

    report: Mapped[Report] = relationship(back_populates="pdf")
    file: Mapped[File] = relationship()


class ReportAttachment(Base):
    __tablename__ = "ReportAttachments"

    file_id: Mapped[int] = mapped_column(
        ForeignKey("Files.file_id", ondelete="CASCADE"), primary_key=True
    )
    report_id: Mapped[int] = mapped_column(
        ForeignKey("Reports.report_id", ondelete="CASCADE"), nullable=False, index=True
    )

    report: Mapped[Report] = relationship(back_populates="attachments")
    file: Mapped[File] = relationship()


class SeriesPlotFile(Base):
    __tablename__ = "SeriesPlotFile"

    series_id: Mapped[int] = mapped_column(
        ForeignKey("DataSeries.series_id", ondelete="CASCADE"), primary_key=True
    )
    file_id: Mapped[int] = mapped_column(
        ForeignKey("Files.file_id", ondelete="CASCADE"), unique=True, nullable=False
    )

    series: Mapped[DataSeries] = relationship(back_populates="plot")
    file: Mapped[File] = relationship()


class FileDeletionQueue(Base):
    __tablename__ = "FileDeletionQueue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
