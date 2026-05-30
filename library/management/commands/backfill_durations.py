import os
import subprocess
import re
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone
from library.models import Movie
from library.views import get_hls_playlist_path, HLS_ROOT

class Command(BaseCommand):
    help = "Backfill duration for already converted movies"

    def handle(self, *args, **options):
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            ffmpeg_exe = "ffmpeg"

        movies = Movie.objects.filter(is_converted=True, duration__isnull=True)
        if not movies.exists():
            self.stdout.write(self.style.SUCCESS("No movies need their duration backfilled!"))
            return

        for movie in movies:
            hls_rel = get_hls_playlist_path(movie.file_path)
            if hls_rel:
                # Remove the /hls/ prefix to get the relative path
                rel_path = hls_rel.replace("/hls/", "", 1) if hls_rel.startswith("/hls/") else hls_rel
                hls_abs = HLS_ROOT / rel_path
                
                if not hls_abs.exists():
                    self.stdout.write(self.style.WARNING(f"Could not find HLS playlist for {movie.title}"))
                    continue

                result = subprocess.run(
                    [ffmpeg_exe, "-i", str(hls_abs)], 
                    capture_output=True, text=True, timeout=20
                )
                
                match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", result.stderr)
                if match:
                    h, m, s = match.groups()
                    sec = int(h) * 3600 + int(m) * 60 + float(s)
                    movie.duration = timezone.timedelta(seconds=sec)
                    movie.save(update_fields=['duration'])
                    self.stdout.write(self.style.SUCCESS(f"Fixed: {movie.title} (Duration: {sec} seconds)"))
                else:
                    self.stdout.write(self.style.ERROR(f"Failed to extract duration for {movie.title}"))
