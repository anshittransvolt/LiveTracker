from django.core.management.base import BaseCommand

from livetracker.services.route_master import build_route_master


class Command(BaseCommand):
    help = (
        "Ingest yesterday's GPS history into the Route Master daily snapshot store and "
        "recluster frequent routes from everything accumulated so far. The vendor GPS API "
        "only retains ~1 day of history, so this only ever ingests 'yesterday' — run it "
        "daily via cron so the snapshot store builds up real day-over-day route repetition "
        "over time (a single run only reveals routes that overlapped within that one day)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--spv", default="NAGPUR", help="Project key, e.g. NAGPUR (default: NAGPUR)")
        parser.add_argument("--days", type=int, default=7, help="How many trailing days of accumulated snapshots to cluster over")
        parser.add_argument("--max-vehicles", type=int, default=None, help="Limit to first N fleet vehicles (debugging)")
        parser.add_argument("--min-occurrences", type=int, default=3, help="Minimum vehicle-days to call a cluster a route")
        parser.add_argument("--workers", type=int, default=6, help="Concurrent fetch_geo requests (raise cautiously — the API rate-limits)")
        parser.add_argument("--force", action="store_true", help="Re-ingest yesterday even if already in the snapshot store")

    def handle(self, *args, **options):
        spv = options["spv"].strip().upper()
        days = options["days"]
        self.stdout.write(f"Ingesting latest day and reclustering frequent routes for {spv} (last {days} days of snapshots)...")

        result = build_route_master(
            spv=spv,
            days=days,
            max_vehicles=options["max_vehicles"],
            min_occurrences=options["min_occurrences"],
            workers=options["workers"],
            force_reingest_latest=options["force"],
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {len(result['routes'])} frequent routes from "
                f"{result['vehicle_days_with_data']} vehicle-days across {result['days_with_snapshots']} "
                f"of the last {days} days ({result['vehicles_analyzed']} vehicles)."
            )
        )
