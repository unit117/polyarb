"""Audit PMXT archive coverage and schema from local files or simple listings.

This is Phase 0 support for the historical live replay plan. The script is
deliberately conservative:

- Prefer auditing local archive files already downloaded to disk.
- Support a text/JSON manifest or a basic HTTP listing as an index source.
- Fail with an explicit blocker when no archive access path is configured.

The output can be written as both JSON and Markdown so the repo can keep a
human-readable audit note under docs/research/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

PARQUET_SUFFIXES = (".parquet", ".parq")
TIMESTAMP_COLUMNS = (
    "timestamp",
    "ts",
    "time",
    "event_time",
    "received_at",
    "created_at",
    "snapshot_time",
    "block_timestamp",
)
MARKET_ID_COLUMNS = (
    "market_id",
    "market",
    "condition_id",
    "question_id",
    "event_id",
)
OUTCOME_ID_COLUMNS = (
    "outcome_id",
    "token_id",
    "asset_id",
    "outcome",
    "outcome_name",
)
HTML_HREF_RE = re.compile(r"""href=["']([^"']+)["']""", re.IGNORECASE)
ISO_HOUR_RE = re.compile(
    r"(?P<year>20\d{2})[-_/](?P<month>\d{2})[-_/](?P<day>\d{2})[Tt _/-]?(?P<hour>\d{2})(?!\d)"
)
PARTITION_HOUR_RE = re.compile(
    r"date=(?P<date>20\d{2}-\d{2}-\d{2}).*?(?:hour|hr|hh)=(?P<hour>\d{1,2})"
)
COMPACT_HOUR_RE = re.compile(
    r"(?P<year>20\d{2})(?P<month>\d{2})(?P<day>\d{2})[_-]?(?P<hour>\d{2})(?!\d)"
)


@dataclass
class ArchiveEntry:
    uri: str
    source: str
    dataset_type: str
    size_bytes: int | None = None
    hour_utc: datetime | None = None
    local_path: str | None = None
    schema_columns: list[str] = field(default_factory=list)
    schema_types: dict[str, str] = field(default_factory=dict)
    row_count: int | None = None
    distinct_markets: int | None = None
    distinct_outcomes: int | None = None
    timestamp_column: str | None = None
    market_id_column: str | None = None
    outcome_id_column: str | None = None
    inspect_error: str | None = None

    @property
    def is_local(self) -> bool:
        return bool(self.local_path)


def infer_dataset_type(uri: str) -> str:
    lower = uri.lower()
    if any(token in lower for token in ("orderbook", "order_book", "book_l2", "/books/", "/order-books/")):
        return "order_book"
    if any(token in lower for token in ("trade", "trades", "/fills/", "/executions/")):
        return "trades"
    return "unknown"


def infer_hour_from_uri(uri: str) -> datetime | None:
    for pattern in (PARTITION_HOUR_RE, ISO_HOUR_RE, COMPACT_HOUR_RE):
        match = pattern.search(uri)
        if not match:
            continue
        groups = match.groupdict()
        if "date" in groups:
            date_part = groups["date"]
            hour = int(groups["hour"])
            dt = datetime.fromisoformat(f"{date_part}T{hour:02d}:00:00+00:00")
            return dt.astimezone(timezone.utc)
        dt = datetime(
            year=int(groups["year"]),
            month=int(groups["month"]),
            day=int(groups["day"]),
            hour=int(groups["hour"]),
            tzinfo=timezone.utc,
        )
        return dt
    return None


def _format_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _format_bytes(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "unknown"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    units = ("KiB", "MiB", "GiB", "TiB")
    value = float(size_bytes)
    for unit in units:
        value /= 1024.0
        if value < 1024.0:
            return f"{value:.2f} {unit}"
    return f"{value:.2f} PiB"


def _pick_evenly(entries: list[ArchiveEntry], limit: int) -> list[ArchiveEntry]:
    if limit <= 0 or len(entries) <= limit:
        return entries
    if limit == 1:
        return [entries[0]]
    selected = []
    last_index = len(entries) - 1
    for i in range(limit):
        index = round(i * last_index / (limit - 1))
        selected.append(entries[index])
    deduped: list[ArchiveEntry] = []
    seen: set[str] = set()
    for entry in selected:
        if entry.uri in seen:
            continue
        deduped.append(entry)
        seen.add(entry.uri)
    return deduped


def discover_local_entries(root: Path) -> list[ArchiveEntry]:
    if not root.exists():
        raise FileNotFoundError(f"Local PMXT root does not exist: {root}")
    files = [
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in PARQUET_SUFFIXES
    ]
    entries: list[ArchiveEntry] = []
    for path in sorted(files):
        stat = path.stat()
        uri = str(path.resolve())
        entries.append(
            ArchiveEntry(
                uri=uri,
                source="local",
                dataset_type=infer_dataset_type(uri),
                size_bytes=stat.st_size,
                hour_utc=infer_hour_from_uri(uri),
                local_path=uri,
            )
        )
    return entries


def _parse_manifest_payload(payload: str, base: str | None = None) -> list[str]:
    stripped = payload.strip()
    if not stripped:
        return []

    urls: list[str] = []
    if stripped.startswith("["):
        data = json.loads(stripped)
        for item in data:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict) and "url" in item:
                urls.append(str(item["url"]))
    elif stripped.startswith("{"):
        data = json.loads(stripped)
        files = data.get("files", [])
        for item in files:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict) and "url" in item:
                urls.append(str(item["url"]))
    elif "<html" in stripped.lower() or "href=" in stripped.lower():
        urls.extend(HTML_HREF_RE.findall(stripped))
    else:
        urls.extend(
            line.strip()
            for line in stripped.splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    normalized: list[str] = []
    for item in urls:
        if base:
            normalized.append(urljoin(base, item))
        else:
            normalized.append(item)
    return [item for item in normalized if item.lower().endswith(PARQUET_SUFFIXES)]


def discover_manifest_entries(manifest_path: Path) -> list[ArchiveEntry]:
    payload = manifest_path.read_text(encoding="utf-8")
    base = None
    if manifest_path.parent:
        base = manifest_path.parent.resolve().as_uri() + "/"
    entries: list[ArchiveEntry] = []
    for item in _parse_manifest_payload(payload, base=base):
        parsed = urlparse(item)
        local_path = None
        size_bytes = None
        source = "manifest"
        if parsed.scheme in ("", "file"):
            local_candidate = Path(parsed.path if parsed.scheme == "file" else item)
            if local_candidate.exists():
                resolved = str(local_candidate.resolve())
                local_path = resolved
                size_bytes = local_candidate.stat().st_size
                item = resolved
                source = "manifest_local"
        entries.append(
            ArchiveEntry(
                uri=item,
                source=source,
                dataset_type=infer_dataset_type(item),
                size_bytes=size_bytes,
                hour_utc=infer_hour_from_uri(item),
                local_path=local_path,
            )
        )
    return entries


def discover_http_index_entries(index_url: str, timeout_seconds: float) -> list[ArchiveEntry]:
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        response = client.get(index_url)
        response.raise_for_status()
        payload = response.text
    urls = _parse_manifest_payload(payload, base=index_url)
    return [
        ArchiveEntry(
            uri=item,
            source="http_index",
            dataset_type=infer_dataset_type(item),
            hour_utc=infer_hour_from_uri(item),
        )
        for item in urls
    ]


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _first_matching_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    lowered = {column.lower(): column for column in columns}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def inspect_local_parquet(entry: ArchiveEntry) -> None:
    if not entry.local_path:
        return

    try:
        import duckdb
    except ModuleNotFoundError as exc:
        entry.inspect_error = (
            "duckdb is not installed; run the audit in the scripts container or install duckdb locally"
        )
        if entry.inspect_error is None:
            entry.inspect_error = str(exc)
        return

    con = duckdb.connect(database=":memory:")
    try:
        describe_rows = con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)",
            [entry.local_path],
        ).fetchall()
        entry.schema_columns = [row[0] for row in describe_rows]
        entry.schema_types = {row[0]: row[1] for row in describe_rows}
        entry.timestamp_column = _first_matching_column(entry.schema_columns, TIMESTAMP_COLUMNS)
        entry.market_id_column = _first_matching_column(entry.schema_columns, MARKET_ID_COLUMNS)
        entry.outcome_id_column = _first_matching_column(entry.schema_columns, OUTCOME_ID_COLUMNS)

        entry.row_count = int(
            con.execute("SELECT COUNT(*) FROM read_parquet(?)", [entry.local_path]).fetchone()[0]
        )
        if entry.market_id_column:
            query = (
                f"SELECT COUNT(DISTINCT {_quote_ident(entry.market_id_column)}) "
                "FROM read_parquet(?)"
            )
            entry.distinct_markets = int(con.execute(query, [entry.local_path]).fetchone()[0])
        if entry.outcome_id_column:
            query = (
                f"SELECT COUNT(DISTINCT {_quote_ident(entry.outcome_id_column)}) "
                "FROM read_parquet(?)"
            )
            entry.distinct_outcomes = int(con.execute(query, [entry.local_path]).fetchone()[0])
        if entry.hour_utc is None and entry.timestamp_column:
            query = (
                f"SELECT MIN(date_trunc('hour', {_quote_ident(entry.timestamp_column)})) "
                "FROM read_parquet(?)"
            )
            value = con.execute(query, [entry.local_path]).fetchone()[0]
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    value = value.replace(tzinfo=timezone.utc)
                entry.hour_utc = value.astimezone(timezone.utc)
    except Exception as exc:  # pragma: no cover - exercised in real runs
        entry.inspect_error = str(exc)
    finally:
        con.close()


def summarize_gaps(hours: list[datetime]) -> list[dict[str, Any]]:
    ordered = sorted({hour.astimezone(timezone.utc) for hour in hours})
    gaps: list[dict[str, Any]] = []
    for earlier, later in zip(ordered, ordered[1:]):
        delta = later - earlier
        if delta <= timedelta(hours=1):
            continue
        missing_hours = int(delta.total_seconds() // 3600) - 1
        gaps.append(
            {
                "after": _format_dt(earlier),
                "before": _format_dt(later),
                "missing_hours": missing_hours,
            }
        )
    gaps.sort(key=lambda item: item["missing_hours"], reverse=True)
    return gaps


def _size_summary(entries: list[ArchiveEntry]) -> dict[str, Any]:
    sizes = [entry.size_bytes for entry in entries if entry.size_bytes is not None]
    if not sizes:
        return {
            "known_file_sizes": 0,
            "total_bytes": None,
            "min_bytes": None,
            "median_bytes": None,
            "max_bytes": None,
        }
    return {
        "known_file_sizes": len(sizes),
        "total_bytes": sum(sizes),
        "min_bytes": min(sizes),
        "median_bytes": int(median(sizes)),
        "max_bytes": max(sizes),
    }


def summarize_joinability(entries: list[ArchiveEntry]) -> dict[str, Any]:
    by_dataset: dict[str, list[ArchiveEntry]] = defaultdict(list)
    for entry in entries:
        by_dataset[entry.dataset_type].append(entry)

    order_books = by_dataset.get("order_book", [])
    trades = by_dataset.get("trades", [])
    if not order_books or not trades:
        return {
            "status": "insufficient_data",
            "reason": "Need both order_book and trades files to evaluate joinability",
        }

    order_columns = {column for entry in order_books for column in entry.schema_columns}
    trade_columns = {column for entry in trades for column in entry.schema_columns}
    shared_columns = order_columns & trade_columns

    shared_id_columns = sorted(
        column
        for column in shared_columns
        if column.lower() in OUTCOME_ID_COLUMNS or column.lower() in MARKET_ID_COLUMNS
    )
    shared_timestamp_columns = sorted(
        column for column in shared_columns if column.lower() in TIMESTAMP_COLUMNS
    )

    status = "joinable" if shared_id_columns and shared_timestamp_columns else "unclear"
    return {
        "status": status,
        "shared_id_columns": shared_id_columns,
        "shared_timestamp_columns": shared_timestamp_columns,
        "note": (
            "Schema-level join check only. Value-level overlap still needs a sample run"
            if status == "joinable"
            else "Could not prove matching outcome/timestamp columns from inspected samples"
        ),
    }


def build_summary(
    entries: list[ArchiveEntry],
    blockers: list[str],
    access: dict[str, Any],
) -> dict[str, Any]:
    hours = [entry.hour_utc for entry in entries if entry.hour_utc is not None]
    inspected = [entry for entry in entries if entry.schema_columns or entry.inspect_error]

    datasets: dict[str, Any] = {}
    grouped: dict[str, list[ArchiveEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.dataset_type].append(entry)

    for dataset_type, dataset_entries in sorted(grouped.items()):
        dataset_hours = [entry.hour_utc for entry in dataset_entries if entry.hour_utc is not None]
        sample_columns = sorted(
            {column for entry in dataset_entries for column in entry.schema_columns}
        )
        datasets[dataset_type] = {
            "file_count": len(dataset_entries),
            "oldest_hour": _format_dt(min(dataset_hours)) if dataset_hours else None,
            "newest_hour": _format_dt(max(dataset_hours)) if dataset_hours else None,
            "size": _size_summary(dataset_entries),
            "sample_schema_columns": sample_columns,
            "sample_row_counts": {
                "files_profiled": sum(1 for entry in dataset_entries if entry.row_count is not None),
                "median_rows": (
                    int(median([entry.row_count for entry in dataset_entries if entry.row_count is not None]))
                    if any(entry.row_count is not None for entry in dataset_entries)
                    else None
                ),
            },
            "distinct_counts_per_profiled_file": [
                {
                    "uri": entry.uri,
                    "hour_utc": _format_dt(entry.hour_utc),
                    "distinct_markets": entry.distinct_markets,
                    "distinct_outcomes": entry.distinct_outcomes,
                }
                for entry in dataset_entries
                if entry.row_count is not None
            ],
            "cadence_gaps": summarize_gaps([hour for hour in dataset_hours if hour is not None])[:10],
        }

    status = "ok"
    if blockers:
        status = "blocked"
    elif not entries:
        status = "blocked"
    elif not inspected:
        status = "partial"

    return {
        "status": status,
        "generated_at": _format_dt(datetime.now(timezone.utc)),
        "access": access,
        "blockers": blockers,
        "archive": {
            "file_count": len(entries),
            "oldest_hour": _format_dt(min(hours)) if hours else None,
            "newest_hour": _format_dt(max(hours)) if hours else None,
            "size": _size_summary(entries),
            "cadence_gaps": summarize_gaps([hour for hour in hours if hour is not None])[:10],
            "datasets": datasets,
            "joinability": summarize_joinability(inspected),
            "inspected_files": [
                {
                    "uri": entry.uri,
                    "dataset_type": entry.dataset_type,
                    "hour_utc": _format_dt(entry.hour_utc),
                    "schema_columns": entry.schema_columns,
                    "inspect_error": entry.inspect_error,
                }
                for entry in inspected
            ],
        },
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# PMXT Archive Audit",
        "",
        f"- Status: `{summary['status']}`",
        f"- Generated: `{summary['generated_at']}`",
        "",
        "## Access",
        "",
        f"- Local root: `{summary['access'].get('local_root') or 'not set'}`",
        f"- Manifest: `{summary['access'].get('manifest') or 'not set'}`",
        f"- HTTP index: `{summary['access'].get('http_index') or 'not set'}`",
        "",
    ]

    blockers = summary.get("blockers", [])
    if blockers:
        lines.extend(["## Blockers", ""])
        for blocker in blockers:
            lines.append(f"- {blocker}")
        lines.append("")

    archive = summary["archive"]
    lines.extend(
        [
            "## Coverage",
            "",
            f"- File count: `{archive['file_count']}`",
            f"- Oldest visible hour: `{archive['oldest_hour'] or 'unknown'}`",
            f"- Newest visible hour: `{archive['newest_hour'] or 'unknown'}`",
            f"- Total known bytes: `{_format_bytes(archive['size']['total_bytes'])}`",
            "",
            "## Datasets",
            "",
        ]
    )
    for dataset_type, dataset in archive["datasets"].items():
        lines.append(f"### {dataset_type}")
        lines.append("")
        lines.append(f"- Files: `{dataset['file_count']}`")
        lines.append(f"- Oldest hour: `{dataset['oldest_hour'] or 'unknown'}`")
        lines.append(f"- Newest hour: `{dataset['newest_hour'] or 'unknown'}`")
        lines.append(f"- Median file size: `{_format_bytes(dataset['size']['median_bytes'])}`")
        lines.append(
            f"- Sample schema columns: `{', '.join(dataset['sample_schema_columns']) or 'not inspected'}`"
        )
        profiled = dataset["distinct_counts_per_profiled_file"]
        if profiled:
            lines.append("- Distinct market/outcome counts from profiled files:")
            for item in profiled[:10]:
                lines.append(
                    "  "
                    f"- `{item['hour_utc'] or item['uri']}` markets={item['distinct_markets']} outcomes={item['distinct_outcomes']}"
                )
        if dataset["cadence_gaps"]:
            lines.append("- Largest cadence gaps:")
            for gap in dataset["cadence_gaps"][:5]:
                lines.append(
                    "  "
                    f"- `{gap['after']}` -> `{gap['before']}` missing `{gap['missing_hours']}` hours"
                )
        lines.append("")

    joinability = archive["joinability"]
    lines.extend(
        [
            "## Joinability",
            "",
            f"- Status: `{joinability['status']}`",
        ]
    )
    if joinability.get("reason"):
        lines.append(f"- Reason: {joinability['reason']}")
    if joinability.get("shared_id_columns"):
        lines.append(
            f"- Shared ID columns: `{', '.join(joinability['shared_id_columns'])}`"
        )
    if joinability.get("shared_timestamp_columns"):
        lines.append(
            f"- Shared timestamp columns: `{', '.join(joinability['shared_timestamp_columns'])}`"
        )
    if joinability.get("note"):
        lines.append(f"- Note: {joinability['note']}")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--local-root",
        default=os.getenv("PMXT_ARCHIVE_ROOT", ""),
        help="Local directory containing PMXT archive parquet files",
    )
    parser.add_argument(
        "--manifest",
        default=os.getenv("PMXT_ARCHIVE_MANIFEST", ""),
        help="Text/JSON manifest listing archive files or URLs",
    )
    parser.add_argument(
        "--http-index",
        default=os.getenv("PMXT_ARCHIVE_INDEX_URL", ""),
        help="HTTP directory listing or index URL containing parquet links",
    )
    parser.add_argument(
        "--inspect-limit-per-dataset",
        type=int,
        default=3,
        help="How many files per dataset to inspect for schema and counts",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=20.0,
        help="Timeout for HTTP index requests",
    )
    parser.add_argument(
        "--summary-json",
        default="",
        help="Optional path to write JSON summary",
    )
    parser.add_argument(
        "--report-md",
        default="",
        help="Optional path to write a Markdown report",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    access = {
        "local_root": args.local_root or None,
        "manifest": args.manifest or None,
        "http_index": args.http_index or None,
    }
    blockers: list[str] = []
    entries: list[ArchiveEntry] = []

    if not any(access.values()):
        blockers.append(
            "No PMXT access path configured. Set --local-root, --manifest, or --http-index "
            "(or PMXT_ARCHIVE_ROOT / PMXT_ARCHIVE_MANIFEST / PMXT_ARCHIVE_INDEX_URL)."
        )
    else:
        if args.local_root:
            try:
                entries.extend(discover_local_entries(Path(args.local_root)))
            except FileNotFoundError as exc:
                blockers.append(str(exc))
        if args.manifest:
            manifest_path = Path(args.manifest)
            if not manifest_path.exists():
                blockers.append(f"Manifest file does not exist: {manifest_path}")
            else:
                entries.extend(discover_manifest_entries(manifest_path))
        if args.http_index:
            try:
                entries.extend(discover_http_index_entries(args.http_index, args.timeout_seconds))
            except Exception as exc:  # pragma: no cover - exercised in real runs
                blockers.append(f"Failed to fetch HTTP index {args.http_index}: {exc}")

    deduped: dict[str, ArchiveEntry] = {}
    for entry in entries:
        deduped.setdefault(entry.uri, entry)
    entries = sorted(
        deduped.values(),
        key=lambda item: (
            item.hour_utc or datetime.max.replace(tzinfo=timezone.utc),
            item.dataset_type,
            item.uri,
        ),
    )

    if not entries and not blockers:
        blockers.append("Configured PMXT access paths produced zero parquet files.")

    grouped: dict[str, list[ArchiveEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.dataset_type].append(entry)
    for dataset_entries in grouped.values():
        for entry in _pick_evenly(dataset_entries, args.inspect_limit_per_dataset):
            inspect_local_parquet(entry)

    summary = build_summary(entries, blockers, access)

    if args.summary_json:
        summary_path = Path(args.summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    markdown = render_markdown(summary)
    if args.report_md:
        report_path = Path(args.report_md)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(markdown + "\n", encoding="utf-8")

    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] != "blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
