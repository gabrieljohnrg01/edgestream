import os
import subprocess
import re
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from library.models import Movie, Episode, ConversionTask
from library.views import get_hls_playlist_path, HLS_ROOT

class Command(BaseCommand):
    help = "Restore is_converted flag and duration for movies/episodes that already have HLS files."

    def handle(self, *args, **options):
        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            ffmpeg_exe = "ffmpeg"

        def get_duration(hls_abs):
            result = subprocess.run([ffmpeg_exe, "-i", str(hls_abs)], capture_output=True, text=True, timeout=20)
            match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", result.stderr)
            if match:
                h, m, s = match.groups()
                sec = int(h) * 3600 + int(m) * 60 + float(s)
                return timezone.timedelta(seconds=sec)
            return None

        # Movies
        for movie in Movie.objects.filter(is_converted=False):
            hls_rel = get_hls_playlist_path(movie.file_path)
            if hls_rel:
                rel_path = hls_rel.replace("/hls/", "", 1) if hls_rel.startswith("/hls/") else hls_rel
                hls_abs = HLS_ROOT / rel_path
                if hls_abs.exists():
                    movie.is_converted = True
                    dur = get_duration(hls_abs)
                    if dur:
                        movie.duration = dur
                    movie.save(update_fields=['is_converted', 'duration'])
                    ConversionTask.objects.filter(movie=movie).delete()
                    self.stdout.write(self.style.SUCCESS(f"Restored movie: {movie.title}"))
                
        # Episodes
        for ep in Episode.objects.filter(is_converted=False):
            hls_rel = get_hls_playlist_path(ep.file_path)
            if hls_rel:
                rel_path = hls_rel.replace("/hls/", "", 1) if hls_rel.startswith("/hls/") else hls_rel
                hls_abs = HLS_ROOT / rel_path
                if hls_abs.exists():
                    ep.is_converted = True
                    dur = get_duration(hls_abs)
                    if dur:
                        ep.duration = dur
                    ep.save(update_fields=['is_converted', 'duration'])
                    ConversionTask.objects.filter(episode=ep).delete()
                    self.stdout.write(self.style.SUCCESS(f"Restored episode: {ep.season.series.title} S{ep.season.season_number}E{ep.episode_number}"))
