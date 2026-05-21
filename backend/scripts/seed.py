"""Seed the development database with realistic-looking sample data.

Usage:
    docker compose run --rm backend python -m scripts.seed
    docker compose run --rm backend python -m scripts.seed --reset

Idempotent: skips if seed users already exist. --reset wipes them first
(cascades through experiments/runs/series/points/reports; orphaned S3
objects are picked up by the worker via FileDeletionQueue).
"""
from __future__ import annotations

import argparse
import asyncio
import io
import math
import random
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from app.core.db import apply_schema, close_pool, get_pool  # noqa: E402  (close_pool used inside main)
from app.core.security import hash_password  # noqa: E402
from app.storage.s3 import ensure_bucket, upload_bytes  # noqa: E402


USERS = [
    ("demo", "demo@example.com"),
    ("alice", "alice@example.com"),
    ("bob", "bob@example.com"),
    ("carol", "carol@example.com"),
    ("dave", "dave@example.com"),
]
COMMON_PASSWORD = "demo123"


@dataclass
class SeriesTemplate:
    name: str
    unit_x: str
    unit_y: str
    description: str
    model: Callable[[float], float]
    x_range: tuple[float, float]
    n_points_range: tuple[int, int]
    noise: float
    x_unc: float | None
    y_unc: float | None


@dataclass
class ExperimentTemplate:
    title: str
    description: str
    series: list[SeriesTemplate]


def _damped(A: float, gamma: float, omega: float):
    return lambda t: A * math.exp(-gamma * t) * math.cos(omega * t)


def _linear(k: float, b: float = 0.0):
    return lambda x: k * x + b


def _exp_decay(V0: float, tau: float):
    return lambda t: V0 * math.exp(-t / tau)


def _falling(y0: float, v0: float, g: float = 9.81):
    return lambda t: y0 + v0 * t - 0.5 * g * t * t


def _sinc2(I0: float, alpha: float):
    def f(x: float) -> float:
        if x == 0.0:
            return I0
        u = alpha * x
        return I0 * (math.sin(u) / u) ** 2
    return f


def _pendulum_period(g: float = 9.81):
    return lambda L: 2 * math.pi * math.sqrt(max(L, 1e-6) / g)


def _boyle(p0: float, v0: float):
    return lambda V: p0 * v0 / max(V, 1e-3)


def _lorentz(amp: float, f0: float, width: float):
    return lambda f: amp / math.sqrt(1.0 + ((f - f0) / width) ** 2)


EXPERIMENTS: list[ExperimentTemplate] = [
    ExperimentTemplate(
        "Затухающие колебания математического маятника",
        "Изучение собственных колебаний маятника длиной 1 м.",
        [SeriesTemplate(
            "Отклонение от равновесия", "t, с", "θ, рад",
            "Угол отклонения маятника",
            _damped(0.25, 0.05, 2 * math.pi / 2.0),
            (0.0, 30.0), (60, 100), 0.005, 0.01, 0.002,
        )],
    ),
    ExperimentTemplate(
        "Проверка закона Ома для металлического проводника",
        "Линейная зависимость I(U) при комнатной температуре.",
        [SeriesTemplate(
            "I(U) для медной проволоки", "U, В", "I, А",
            "Сила тока через медный образец",
            _linear(0.42), (0.0, 10.0), (40, 60), 0.02, 0.05, 0.01,
        )],
    ),
    ExperimentTemplate(
        "Разряд конденсатора через резистор",
        "RC-цепь: C=100 мкФ, R=10 кОм.",
        [SeriesTemplate(
            "U(t) на конденсаторе", "t, с", "U, В",
            "Напряжение на ёмкости при разряде",
            _exp_decay(5.0, 1.0), (0.0, 6.0), (60, 80), 0.03, 0.01, 0.02,
        )],
    ),
    ExperimentTemplate(
        "Свободное падение тела",
        "Регистрация координаты с шагом 0.025 с.",
        [SeriesTemplate(
            "y(t)", "t, с", "y, м",
            "Падение тела с высоты 5 м",
            _falling(5.0, 0.0), (0.0, 1.0), (40, 60), 0.01, 0.005, 0.01,
        )],
    ),
    ExperimentTemplate(
        "Дифракция Фраунгофера на одной щели",
        "Лазер 650 нм, щель 0.1 мм.",
        [SeriesTemplate(
            "I(α)", "α, рад", "I, отн. ед.",
            "Распределение интенсивности",
            _sinc2(1.0, 30.0), (-0.2, 0.2), (80, 120), 0.01, 0.001, 0.005,
        )],
    ),
    ExperimentTemplate(
        "Тепловое расширение алюминиевого стержня",
        "Удлинение стержня L₀=500 мм при нагреве.",
        [SeriesTemplate(
            "ΔL(T)", "T, °C", "ΔL, мм",
            "Изменение длины образца",
            _linear(0.0119), (20.0, 100.0), (30, 50), 0.02, 0.5, 0.01,
        )],
    ),
    ExperimentTemplate(
        "Зависимость периода маятника от длины",
        "T = 2π√(L/g) — проверка квадратичной модели.",
        [SeriesTemplate(
            "T(L)", "L, м", "T, с",
            "Период колебаний",
            _pendulum_period(), (0.1, 1.5), (15, 25), 0.02, 0.005, 0.05,
        )],
    ),
    ExperimentTemplate(
        "Закон Бойля-Мариотта",
        "Изотермический процесс с воздухом в шприце.",
        [SeriesTemplate(
            "P(V)", "V, мл", "P, кПа",
            "Давление в шприце",
            _boyle(101.3, 50.0), (20.0, 80.0), (20, 40), 0.5, 0.5, 1.0,
        )],
    ),
    ExperimentTemplate(
        "Резонансная кривая RLC-контура",
        "Зависимость амплитуды от частоты.",
        [SeriesTemplate(
            "U(f)", "f, кГц", "U, В",
            "Амплитуда на ёмкости",
            _lorentz(5.0, 5.0, 0.3), (3.0, 7.0), (40, 60), 0.05, 0.01, 0.02,
        )],
    ),
    ExperimentTemplate(
        "Калибровка термопары типа K",
        "Диапазон 0–200 °C.",
        [SeriesTemplate(
            "U(T)", "T, °C", "U, мВ",
            "ЭДС термопары",
            _linear(0.041, -0.05), (0.0, 200.0), (30, 50), 0.05, 0.5, 0.02,
        )],
    ),
]


def gen_points(t: SeriesTemplate, rng: random.Random):
    n = rng.randint(*t.n_points_range)
    x0, x1 = t.x_range
    out = []
    for i in range(n):
        x = x0 + (x1 - x0) * i / max(n - 1, 1)
        y = t.model(x) + rng.gauss(0.0, t.noise)
        out.append((i + 1, x, y, t.x_unc, t.y_unc))
    return out


def render_plot(t: SeriesTemplate, pts) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 5))
    xs = [p[1] for p in pts]
    ys = [p[2] for p in pts]
    xerr = [p[3] or 0.0 for p in pts]
    yerr = [p[4] or 0.0 for p in pts]
    ax.errorbar(xs, ys, xerr=xerr, yerr=yerr, fmt="o-", capsize=3, markersize=3)
    ax.set_title(t.name)
    ax.set_xlabel(t.unit_x)
    ax.set_ylabel(t.unit_y)
    ax.grid(True, alpha=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def render_run_image(title: str, run_number: int) -> bytes:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.text(0.5, 0.6, title, ha="center", va="center", fontsize=12, wrap=True)
    ax.text(0.5, 0.4, f"Запуск №{run_number}", ha="center", va="center",
            fontsize=10, alpha=0.7)
    ax.set_axis_off()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=80, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def render_attachment_photo(title: str, idx: int, rng: random.Random) -> bytes:
    """Synthetic "photo" for a report attachment — simple scatter to look like lab data."""
    fig, ax = plt.subplots(figsize=(6, 4))
    n = rng.randint(20, 60)
    xs = [rng.uniform(0, 10) for _ in range(n)]
    ys = [rng.gauss(x * 0.5 + 1, 0.4) for x in xs]
    ax.scatter(xs, ys, s=20, alpha=0.7)
    ax.set_title(f"{title} — фото {idx}", fontsize=10)
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.grid(True, alpha=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=80, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def make_tex(title: str, run_number: int) -> bytes:
    return (
        "\\documentclass{article}\n"
        "\\usepackage[utf8]{inputenc}\n"
        "\\usepackage[T2A]{fontenc}\n"
        "\\usepackage[russian]{babel}\n"
        f"\\title{{{title} — запуск {run_number}}}\n"
        "\\begin{document}\\maketitle\n"
        "Демонстрационный отчёт, сгенерированный скриптом seed.\n"
        "\\end{document}\n"
    ).encode("utf-8")


def make_pdf(title: str, run_number: int) -> bytes:
    fig, ax = plt.subplots(figsize=(8.27, 11.69))  # A4
    ax.text(0.5, 0.55, title, ha="center", va="center", fontsize=20, wrap=True)
    ax.text(0.5, 0.45, f"Запуск №{run_number}", ha="center", va="center",
            fontsize=14, alpha=0.7)
    ax.text(0.5, 0.05, "Демонстрационный отчёт (seed)",
            ha="center", va="center", fontsize=9, alpha=0.5)
    ax.set_axis_off()
    buf = io.BytesIO()
    fig.savefig(buf, format="pdf", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


async def insert_file(conn, mime: str, content: bytes, final_path_fn):
    """Two-step insert: temp path → real path (which embeds file_id) → S3 upload."""
    temp = f"_uploading/{uuid.uuid4()}"
    row = await conn.fetchrow(
        'INSERT INTO "Files" (mime_type, storage_path, size_bytes) '
        "VALUES ($1, $2, $3) RETURNING file_id",
        mime, temp, len(content),
    )
    file_id = row["file_id"]
    final = final_path_fn(file_id)
    await conn.execute(
        'UPDATE "Files" SET storage_path = $1 WHERE file_id = $2', final, file_id,
    )
    await upload_bytes(final, content, mime)
    return file_id


async def attach_series_plot(conn, series_id: int, t: SeriesTemplate, pts):
    png = render_plot(t, pts)
    file_id = await insert_file(
        conn, "image/png", png, lambda fid: f"plots/{series_id}/{fid}.png",
    )
    await conn.execute(
        'INSERT INTO "SeriesPlotFile" (series_id, file_id) VALUES ($1, $2)',
        series_id, file_id,
    )


async def attach_run_image(conn, run_id: int, title: str, run_number: int):
    png = render_run_image(title, run_number)
    file_id = await insert_file(
        conn, "image/png", png, lambda fid: f"images/{run_id}/{fid}.png",
    )
    await conn.execute(
        'INSERT INTO "RunImages" (file_id, run_id) VALUES ($1, $2)',
        file_id, run_id,
    )


async def attach_report(conn, run_id: int, title: str, run_number: int,
                        rng: random.Random, stats: dict):
    row = await conn.fetchrow(
        'INSERT INTO "Reports" (run_id, title) VALUES ($1, $2) RETURNING report_id',
        run_id, f"Отчёт: {title} (запуск {run_number})",
    )
    report_id = row["report_id"]

    tex = make_tex(title, run_number)
    tex_id = await insert_file(
        conn, "application/x-tex", tex, lambda _fid: f"reports/{report_id}/report.tex",
    )
    await conn.execute(
        'INSERT INTO "ReportSourceFile" (report_id, file_id) VALUES ($1, $2)',
        report_id, tex_id,
    )

    pdf = make_pdf(title, run_number)
    pdf_id = await insert_file(
        conn, "application/pdf", pdf, lambda _fid: f"reports/{report_id}/report.pdf",
    )
    await conn.execute(
        'INSERT INTO "ReportPdfFile" (report_id, file_id) VALUES ($1, $2)',
        report_id, pdf_id,
    )

    for idx in range(1, rng.randint(2, 4)):
        png = render_attachment_photo(title, idx, rng)
        file_id = await insert_file(
            conn, "image/png", png, lambda fid: f"reports/{report_id}/{fid}.png",
        )
        await conn.execute(
            'INSERT INTO "ReportAttachments" (file_id, report_id) VALUES ($1, $2)',
            file_id, report_id,
        )
        stats["attachments"] += 1


async def seed_user_payload(conn, username: str, email: str, pw_hash: str,
                            rng: random.Random, stats: dict):
    urow = await conn.fetchrow(
        'INSERT INTO "Users" (username, email, password_hash) '
        "VALUES ($1, $2, $3) RETURNING user_id",
        username, email, pw_hash,
    )
    user_id = urow["user_id"]
    print(f"  user: {username} (id={user_id})")

    templates = rng.sample(EXPERIMENTS, k=len(EXPERIMENTS))
    for tmpl in templates:
        erow = await conn.fetchrow(
            'INSERT INTO "Experiments" (user_id, title, description) '
            "VALUES ($1, $2, $3) RETURNING experiment_id",
            user_id, tmpl.title, tmpl.description,
        )
        experiment_id = erow["experiment_id"]
        stats["experiments"] += 1

        for ri in range(rng.randint(3, 5)):
            rrow = await conn.fetchrow(
                'INSERT INTO "ExperimentRuns" (experiment_id, run_number, name, description) '
                "VALUES ($1, 0, $2, $3) RETURNING run_id, run_number",
                experiment_id, f"Запуск {ri + 1}", f"Серия измерений №{ri + 1}",
            )
            run_id = rrow["run_id"]
            run_number = rrow["run_number"]
            stats["runs"] += 1

            if rng.random() < 0.20:
                await attach_run_image(conn, run_id, tmpl.title, run_number)
                stats["images"] += 1

            if rng.random() < 0.50:
                await attach_report(conn, run_id, tmpl.title, run_number, rng, stats)
                stats["reports"] += 1

            for _ in range(rng.randint(1, 2)):
                t = rng.choice(tmpl.series)
                pts = gen_points(t, rng)
                srow = await conn.fetchrow(
                    'INSERT INTO "DataSeries" '
                    "(run_id, series_name, unit_x, unit_y, description) "
                    "VALUES ($1, $2, $3, $4, $5) RETURNING series_id",
                    run_id, t.name, t.unit_x, t.unit_y, t.description,
                )
                series_id = srow["series_id"]
                await conn.executemany(
                    'INSERT INTO "DataPoints" '
                    "(series_id, measurement_order, x_value, y_value, "
                    "x_uncertainty, y_uncertainty) "
                    "VALUES ($1, $2, $3, $4, $5, $6)",
                    [(series_id, *p) for p in pts],
                )
                stats["series"] += 1
                stats["points"] += len(pts)

                if rng.random() < 0.30:
                    await attach_series_plot(conn, series_id, t, pts)
                    stats["plots"] += 1


async def main(reset_flag: bool) -> int:
    print("Применяем схему...")
    await apply_schema()
    print("Проверяем bucket в MinIO...")
    await ensure_bucket()

    pool = await get_pool()
    rng = random.Random(42)
    usernames = [u[0] for u in USERS]

    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            'SELECT COUNT(*) FROM "Users" WHERE username = ANY($1::text[])',
            usernames,
        )
        if existing and not reset_flag:
            print(
                f"Найдено {existing} seed-пользователей — пропускаю. "
                "Используйте --reset для повторной генерации."
            )
            return 0

        if reset_flag and existing:
            print(f"--reset: удаляю {existing} существующих seed-пользователей...")
            await conn.execute(
                'DELETE FROM "Users" WHERE username = ANY($1::text[])', usernames,
            )

        print("Хеширую пароль...")
        pw_hash = hash_password(COMMON_PASSWORD)

        stats = {"experiments": 0, "runs": 0, "series": 0, "points": 0,
                 "plots": 0, "images": 0, "reports": 0, "attachments": 0}

        for username, email in USERS:
            async with conn.transaction():
                await seed_user_payload(conn, username, email, pw_hash, rng, stats)

    print()
    print("Готово.")
    print(f"  пользователи:   {len(USERS)}")
    print(f"  эксперименты:   {stats['experiments']}")
    print(f"  запуски:        {stats['runs']}")
    print(f"  серии:          {stats['series']}")
    print(f"  точки данных:   {stats['points']}")
    print(f"  графики (PNG):  {stats['plots']}")
    print(f"  изображения:    {stats['images']}")
    print(f"  отчёты:         {stats['reports']}")
    print(f"  вложения фото:  {stats['attachments']}")
    print()
    print(f"Логин: demo / {COMMON_PASSWORD}  (или alice, bob, carol, dave — тот же пароль).")
    await close_pool()
    return 0


def cli() -> int:
    parser = argparse.ArgumentParser(description="Seed development data.")
    parser.add_argument("--reset", action="store_true",
                        help="Удалить существующих seed-пользователей перед генерацией.")
    args = parser.parse_args()
    return asyncio.run(main(reset_flag=args.reset))


if __name__ == "__main__":
    sys.exit(cli())
