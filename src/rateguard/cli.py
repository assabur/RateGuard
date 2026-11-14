import argparse
import json
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .config import Settings
from .demo import DEMO_DATE


def main():
    parser = argparse.ArgumentParser(description="US yield monitoring and provider reconciliation")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser(
        "demo", help="Run synthetic fixtures without provider credentials (requires PostgreSQL)"
    )
    demo.add_argument("--as-of", type=date.fromisoformat, default=DEMO_DATE)
    ingest = commands.add_parser("ingest", help="Collect Treasury XML and FRED observations")
    ingest.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=datetime.now(ZoneInfo("America/New_York")).date(),
    )
    serve = commands.add_parser("serve", help="Dashboard, read-only API and Swagger documentation")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        parser.error(str(exc))
    if args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(settings), host=args.host, port=args.port)
        return
    if args.as_of > datetime.now(ZoneInfo("America/New_York")).date():
        parser.error("--as-of cannot be in the future")
    from .pipeline import run_pipeline

    try:
        report = run_pipeline(settings, args.as_of, "demo" if args.command == "demo" else "live")
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, allow_nan=False))
    # Demo deliberately contains all severity levels, so it exits successfully.
    if args.command == "ingest" and report["status"] == "CRITICAL":
        print(
            "CRITICAL: report persisted; inspect ingestion_errors and quality_issues.",
            file=sys.stderr,
        )
        raise SystemExit(1)
