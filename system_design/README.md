# Система отслеживания физических экспериментов

Система позволяет отслеживать версии физических экспериментов: хранить параметры запусков, измеренные данные, отчёты и связанные файлы.

Метаданные хранятся в **PostgreSQL** (схема нормализована до 5НФ), бинарные файлы — в **S3-совместимом хранилище (MinIO)**.

---

## S3 — структура хранения

```
images/{run_id}/{file_id}.png
reports/{report_id}/report.tex
reports/{report_id}/report.pdf
reports/{report_id}/{file_id}.jpg
plots/{series_id}/{file_id}.png
```

В БД хранится только ключ объекта (`storage_path`), физическое удаление файлов из S3 выполняется фоновым воркером через outbox-таблицу `FileDeletionQueue`.

---
## ER модель
Связи:
ExperimentRun -> Files - хранение изображений

Reports -> Files - хранение данных отчетов (pdf + latex + картинки)

DataSeries -> Files - хранение автосгенерированных графиков

Поле FileRole - source/pdf/.. - чтобы для reports отличать
![ER-модель](/assets/ER.drawio.svg)

## Реляционная модель до нормализации:

![](/assets/relational_not_norm.svg)
---
##  [Реляционная модель после нормализации]
![](/assets/relational.svg)

## Описание таблиц

#### Users

| Колонка | Тип | Ключ | Nullable | Constraint | Описание |
|:---|:---|:---|:---|:---|:---|
| user_id | integer | PK | NOT NULL | IDENTITY | Идентификатор пользователя |
| username | varchar(64) | — | NOT NULL | UNIQUE | Логин |
| email | varchar(254) | — | NOT NULL | UNIQUE | Адрес электронной почты |
| created_at | timestamptz | — | NOT NULL | `NOW()` | Метка регистрации |

---

### Основные сущности

#### Experiments

| Колонка | Тип | Ключ | Nullable | Constraint | Описание |
|:---|:---|:---|:---|:---|:---|
| experiment_id | integer | PK | NOT NULL | IDENTITY | Идентификатор эксперимента |
| user_id | integer | FK → Users | NOT NULL | — | Владелец |
| title | varchar(200) | — | NOT NULL | — | Название |
| description | text | — | NULL | — | Описание в свободной форме |
| created_at | timestamptz | — | NOT NULL | `NOW()` | Метка создания |
| updated_at | timestamptz | — | NOT NULL | `NOW()` | Метка последнего изменения |

#### ExperimentRuns

Каждый запуск — отдельная попытка / версия эксперимента.

| Колонка | Тип | Ключ | Nullable | Constraint | Описание |
|:---|:---|:---|:---|:---|:---|
| run_id | integer | PK | NOT NULL | IDENTITY | Идентификатор запуска |
| experiment_id | integer | FK → Experiments | NOT NULL | — | Родительский эксперимент |
| run_number | integer | — | NOT NULL | UNIQUE(experiment_id, run_number) | Порядковый номер попытки внутри эксперимента |
| name | varchar(200) | — | NOT NULL | — | Метка запуска |
| description | text | — | NULL | — | Заметки |
| created_at | timestamptz | — | NOT NULL | `NOW()` | Метка создания |
| updated_at | timestamptz | — | NOT NULL | `NOW()` | Метка последнего изменения |

#### DataSeries

Метаданные серии данных (графика), прикреплённой к запуску.

| Колонка | Тип | Ключ | Nullable | Constraint | Описание |
|:---|:---|:---|:---|:---|:---|
| series_id | integer | PK | NOT NULL | IDENTITY | Идентификатор серии |
| run_id | integer | FK → ExperimentRuns | NOT NULL | — | Родительский запуск |
| series_name | varchar(100) | — | NOT NULL | — | Заголовок графика |
| unit_x | varchar(32) | — | NULL | — | Единица оси X (например, «с») |
| unit_y | varchar(32) | — | NULL | — | Единица оси Y (например, «м/с²») |
| description | text | — | NULL | — | Описание серии |
| created_at | timestamptz | — | NOT NULL | `NOW()` | Метка создания |
| updated_at | timestamptz | — | NOT NULL | `NOW()` | Метка последнего изменения |

#### DataPoints

Измеренные точки данных в рамках серии.

| Колонка | Тип | Ключ | Nullable | Constraint | Описание |
|:---|:---|:---|:---|:---|:---|
| point_id | integer | PK | NOT NULL | IDENTITY | Идентификатор точки |
| series_id | integer | FK → DataSeries | NOT NULL | — | Родительская серия |
| measurement_order | integer | — | NOT NULL | UNIQUE(series_id, measurement_order) | Порядок измерения внутри серии |
| x_value | double precision | — | NOT NULL | — | Значение X |
| y_value | double precision | — | NOT NULL | — | Значение Y |
| x_uncertainty | double precision | — | NULL | CHECK ≥ 0 | Погрешность X (±) |
| y_uncertainty | double precision | — | NULL | CHECK ≥ 0 | Погрешность Y (±) |
| created_at | timestamptz | — | NOT NULL | `NOW()` | Метка записи точки |

Поле `measurement_order` сохраняет порядок повторных измерений (реляционная модель — это множество, порядок строк не гарантирован).

#### Reports

Отчёты, прикреплённые к запуску.

| Колонка | Тип | Ключ | Nullable | Constraint | Описание |
|:---|:---|:---|:---|:---|:---|
| report_id | integer | PK | NOT NULL | IDENTITY | Идентификатор отчёта |
| run_id | integer | FK → ExperimentRuns | NOT NULL | — | Родительский запуск |
| title | varchar(200) | — | NOT NULL | DEFAULT 'Untitled' | Заголовок |
| created_at | timestamptz | — | NOT NULL | `NOW()` | Метка создания |
| updated_at | timestamptz | — | NOT NULL | `NOW()` | Метка последнего изменения |

---

### Файлы и связи

Файлы хранятся в одной общей таблице `Files` с минимальным набором атрибутов. Принадлежность файла к контексту (запуск, отчёт, серия) выражается через отдельные связующие таблицы. Это устраняет транзитивные зависимости и NULL-FK исходной модели.

#### Files

| Колонка | Тип | Ключ | Nullable | Constraint | Описание |
|:---|:---|:---|:---|:---|:---|
| file_id | integer | PK | NOT NULL | IDENTITY | Идентификатор файла |
| mime_type | varchar(127) | — | NOT NULL | — | MIME-тип (например, `image/png`) |
| storage_path | text | — | NOT NULL | UNIQUE | Полный ключ объекта S3 |
| size_bytes | bigint | — | NOT NULL | CHECK ≥ 0 | Размер в байтах |
| uploaded_at | timestamptz | — | NOT NULL | `NOW()` | Метка загрузки |

#### RunImages — изображения уровня запуска (1:N)

| Колонка | Тип | Ключ | Constraint |
|:---|:---|:---|:---|
| file_id | integer | PK, FK → Files | ON DELETE CASCADE |
| run_id | integer | FK → ExperimentRuns, NOT NULL | ON DELETE CASCADE |

`file_id` как единственный PK обеспечивает, что один файл не может одновременно быть картинкой двух запусков. Составной PK `(run_id, file_id)` был бы избыточен: `file_id` — кандидатный ключ, и иметь не минимальный PK означало бы нарушение BCNF.

#### ReportSourceFile — исходник отчёта `.tex` (1:1)

| Колонка | Тип | Ключ | Constraint |
|:---|:---|:---|:---|
| report_id | integer | PK, FK → Reports | ON DELETE CASCADE |
| file_id | integer | FK → Files, UNIQUE | ON DELETE CASCADE |

#### ReportPdfFile — собранный PDF отчёта (1:1)

| Колонка | Тип | Ключ | Constraint |
|:---|:---|:---|:---|
| report_id | integer | PK, FK → Reports | ON DELETE CASCADE |
| file_id | integer | FK → Files, UNIQUE | ON DELETE CASCADE |

#### ReportAttachments — вложения отчёта, картинки внутри отчёта (1:N)

| Колонка | Тип | Ключ | Constraint |
|:---|:---|:---|:---|
| file_id | integer | PK, FK → Files | ON DELETE CASCADE |
| report_id | integer | FK → Reports, NOT NULL | ON DELETE CASCADE |

По аналогии с `RunImages`: `file_id` — кандидатный ключ, поэтому он является единственным PK. Это гарантирует, что один файл-вложение не может принадлежать двум разным отчётам.

#### SeriesPlotFile — авто-плот серии данных (1:1)

| Колонка | Тип | Ключ | Constraint |
|:---|:---|:---|:---|
| series_id | integer | PK, FK → DataSeries | ON DELETE CASCADE |
| file_id | integer | FK → Files, UNIQUE | ON DELETE CASCADE |

---

### Инвариант «у файла ровно один владелец»

В ER-модели все связи `Files` с junction-таблицами опциональны с обеих сторон (`Files ||--o| RunImages` и т.д.), поэтому на уровне схемы допустима запись в `Files`, не связанная ни с одной junction-таблицей («осиротевший» файл). Выразить декларативно «ровно один владелец из N таблиц» в 5НФ без дискриминирующего атрибута невозможно — это ломало бы нормализацию (дискриминатор дублировал бы информацию, уже выраженную наличием строки в соответствующей junction-таблице).

Поэтому инвариант обеспечивается на уровне **сервисного слоя**, а не БД:

1. Загрузка файла и вставка связи в junction-таблицу выполняются в одной транзакции FastAPI-хендлера. Вставка в `Files` без последующей связи считается ошибкой приложения.
2. Периодический GC-воркер находит строки `Files`, на которые не ссылается ни одна из junction-таблиц (`RunImages`, `ReportSourceFile`, `ReportPdfFile`, `ReportAttachments`, `SeriesPlotFile`), и удаляет их — триггер `trg_file_outbox` далее ставит `storage_path` в `FileDeletionQueue`, и файл асинхронно удаляется из S3.

Альтернатива (отложенный `AFTER INSERT` триггер, проверяющий наличие связи на `COMMIT`) была отвергнута: усложняет схему и плохо взаимодействует с batch-загрузками.

---

### Служебные таблицы

#### FileDeletionQueue (outbox для очистки S3)

Транзакционно-надёжная очередь удаления файлов из S3. Триггер `AFTER DELETE` на `Files` пишет сюда строку, фоновый воркер её обрабатывает и проставляет `processed_at`. В отличие от `pg_notify`, это переживает падение слушателя и допускает ретраи.

| Колонка | Тип | Ключ | Nullable | Constraint | Описание |
|:---|:---|:---|:---|:---|:---|
| id | bigint | PK | NOT NULL | IDENTITY | — |
| storage_path | text | — | NOT NULL | — | Ключ объекта в S3 |
| queued_at | timestamptz | — | NOT NULL | `NOW()` | Время постановки в очередь |
| processed_at | timestamptz | — | NULL | — | Время успешной обработки |
| retry_count | integer | — | NOT NULL | DEFAULT 0 | Число попыток обработки |
| last_error | text | — | NULL | — | Текст последней ошибки |

Дополнительно создаётся частичный уникальный индекс, предотвращающий дублирование pending-записей для одного и того же пути:

```sql
CREATE UNIQUE INDEX uq_file_deletion_queue_pending
  ON FileDeletionQueue (storage_path)
  WHERE processed_at IS NULL;
```

Это не мешает повторной постановке в очередь уже удалённого файла (если путь в S3 был переиспользован), но исключает дублирующие задания для ещё не обработанной записи.

---

## Триггеры и ограничения целостности

| # | Объект | Тип | Событие | Целевая таблица | Действие | Обоснование |
|:---|:---|:---|:---|:---|:---|:---|
| 0 | `Experiments.user_id` | FK | ON DELETE CASCADE | Users | Удаляет все эксперименты пользователя | Эксперимент не существует без владельца |
| 1 | `ExperimentRuns.experiment_id` | FK | ON DELETE CASCADE | Experiments | Удаляет все запуски эксперимента | Запуск не существует без эксперимента |
| 2 | `DataSeries.run_id` | FK | ON DELETE CASCADE | ExperimentRuns | Удаляет все серии запуска | Серия не существует без запуска |
| 3 | `DataPoints.series_id` | FK | ON DELETE CASCADE | DataSeries | Удаляет все точки серии | Точка не существует без серии |
| 4 | `Reports.run_id` | FK | ON DELETE CASCADE | ExperimentRuns | Удаляет все отчёты запуска | Отчёт не существует без запуска |
| 5 | Связующие таблицы файлов | FK | ON DELETE CASCADE | Files / parents | Удаляет связь при удалении любой стороны | Связь без обеих сторон бессмысленна |
| 6 | `trg_run_number` | TRIGGER | BEFORE INSERT | ExperimentRuns | `pg_advisory_xact_lock(experiment_id)` → `run_number = COALESCE(MAX(run_number),0)+1`, защищён `UNIQUE(experiment_id, run_number)` | Автоинкремент номера попытки; advisory lock предотвращает гонку при параллельных вставках |
| 7 | `trg_updated_at_experiments` | TRIGGER | BEFORE UPDATE | Experiments | `updated_at = NOW()` | Автообновление метки |
| 8 | `trg_updated_at_runs` | TRIGGER | BEFORE UPDATE | ExperimentRuns | `updated_at = NOW()` | Автообновление метки |
| 9 | `trg_file_outbox` | TRIGGER | AFTER DELETE | Files | `INSERT INTO FileDeletionQueue(storage_path) ... ON CONFLICT DO NOTHING` | Транзакционно-надёжная очистка S3; `ON CONFLICT` защищает от конфликта с частичным уникальным индексом при повторном использовании пути |
| 10 | `trg_updated_at_series` | TRIGGER | BEFORE UPDATE | DataSeries | `updated_at = NOW()` | Автообновление метки |
| 11 | `trg_updated_at_reports` | TRIGGER | BEFORE UPDATE | Reports | `updated_at = NOW()` | Автообновление метки |
| 12 | `CHECK` на погрешностях | CHECK | — | DataPoints | `x_uncertainty ≥ 0`, `y_uncertainty ≥ 0` | Погрешность не может быть отрицательной |
| 13 | `CHECK` на размере файла | CHECK | — | Files | `size_bytes ≥ 0` | Размер не может быть отрицательным |

---

