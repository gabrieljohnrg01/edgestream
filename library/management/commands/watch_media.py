import os
import sys
import time
from pathlib import Path
from threading import Event, Timer

from django.conf import settings
from django.core.management import BaseCommand, call_command

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(settings.MEDIA_ROOT)))
WATCH_DIRS = [MEDIA_ROOT / "movies", MEDIA_ROOT / "series"]
WATCHED_EXTENSIONS = {".mp4", ".mkv", ".avi"}
DEBOUNCE_SECONDS = 2.0


def _normalize_path(path):
    return str(Path(path).resolve())


class DebouncedScan:
    def __init__(self):
        self.timer = None
        self.event = Event()

    def schedule(self):
        if self.timer:
            self.timer.cancel()
        self.timer = Timer(DEBOUNCE_SECONDS, self.run)
        self.timer.daemon = True
        self.timer.start()

    def run(self):
        self.event.set()
        self.timer = None
        try:
            call_command("scan_media")
        except Exception as exc:
            sys.stderr.write(f"Error running scan_media: {exc}\n")


class Command(BaseCommand):
    help = "Watch media folders and automatically scan new movies/episodes for conversion."

    def add_arguments(self, parser):
        parser.add_argument(
            "--initial-scan",
            action="store_true",
            help="Run an initial scan before watching for changes.",
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting media watcher..."))

        if options["initial_scan"]:
            self.stdout.write(self.style.NOTICE("Running initial media scan..."))
            call_command("scan_media")

        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            self.stderr.write(
                "The watchdog package is required for file watching. Install it with `pip install watchdog`."
            )
            return

        cmd = self
        scan = DebouncedScan()

        class MediaEventHandler(FileSystemEventHandler):
            def on_created(self, event):
                self._handle(event)

            def on_moved(self, event):
                self._handle(event)

            def on_modified(self, event):
                self._handle(event)

            def _handle(self, event):
                path = event.dest_path if hasattr(event, "dest_path") else getattr(event, "src_path", None)
                if not path or event.is_directory:
                    return
                extension = Path(path).suffix.lower()
                if extension in WATCHED_EXTENSIONS:
                    cmd.stdout.write(cmd.style.SUCCESS(f"Detected new/changed media: {path}"))
                    scan.schedule()

        observer = Observer()
        handler = MediaEventHandler()

        for watch_dir in WATCH_DIRS:
            watch_dir.mkdir(parents=True, exist_ok=True)
            observer.schedule(handler, str(watch_dir), recursive=True)
            self.stdout.write(self.style.NOTICE(f"Watching {watch_dir}"))

        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Stopping media watcher..."))
            observer.stop()
        observer.join()
