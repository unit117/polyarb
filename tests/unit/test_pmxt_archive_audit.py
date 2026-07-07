from datetime import datetime, timezone

from scripts.pmxt_archive_audit import (
    _parse_manifest_payload,
    build_summary,
    infer_dataset_type,
    infer_hour_from_uri,
    render_markdown,
    summarize_gaps,
)


def test_infer_dataset_type_from_common_names():
    assert infer_dataset_type("/tmp/order_book/2026-03-25/14.parquet") == "order_book"
    assert infer_dataset_type("/tmp/trades/2026-03-25/14.parquet") == "trades"
    assert infer_dataset_type("/tmp/misc/2026-03-25/14.parquet") == "unknown"


def test_infer_hour_from_uri_supports_multiple_layouts():
    assert infer_hour_from_uri("s3://bucket/order_book/2026/03/25/14/file.parquet") == datetime(
        2026, 3, 25, 14, tzinfo=timezone.utc
    )
    assert infer_hour_from_uri("https://x/archive/date=2026-03-25/hour=7/file.parquet") == datetime(
        2026, 3, 25, 7, tzinfo=timezone.utc
    )
    assert infer_hour_from_uri("/tmp/2026032519_trades.parquet") == datetime(
        2026, 3, 25, 19, tzinfo=timezone.utc
    )


def test_parse_manifest_payload_supports_lines_and_html():
    payload = """
    # comment
    https://example.com/order_book/2026-03-25/14.parquet
    https://example.com/trades/2026-03-25/14.parquet
    """
    assert _parse_manifest_payload(payload) == [
        "https://example.com/order_book/2026-03-25/14.parquet",
        "https://example.com/trades/2026-03-25/14.parquet",
    ]

    html = '<a href="order_book/2026-03-25/14.parquet">book</a>'
    assert _parse_manifest_payload(html, base="https://example.com/archive/") == [
        "https://example.com/archive/order_book/2026-03-25/14.parquet"
    ]


def test_summarize_gaps_reports_missing_hours():
    gaps = summarize_gaps(
        [
            datetime(2026, 3, 25, 10, tzinfo=timezone.utc),
            datetime(2026, 3, 25, 11, tzinfo=timezone.utc),
            datetime(2026, 3, 25, 14, tzinfo=timezone.utc),
        ]
    )
    assert gaps == [
        {
            "after": "2026-03-25T11:00:00Z",
            "before": "2026-03-25T14:00:00Z",
            "missing_hours": 2,
        }
    ]


def test_render_markdown_includes_blockers():
    summary = build_summary(
        entries=[],
        blockers=["No PMXT access path configured."],
        access={"local_root": None, "manifest": None, "http_index": None},
    )
    markdown = render_markdown(summary)
    assert "Status: `blocked`" in markdown
    assert "No PMXT access path configured." in markdown
