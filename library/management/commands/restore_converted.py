import os
import subprocess
import re
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from library.models import Movie, Episode, ConversionTask
from library.views import get_hls_playlist_path, HLS_ROOT
from library.tmdb import extract_title_year, fetch_tmdb_metadata, parse_date, TMDB_IMAGE_BASE

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

        # Rebuild missing movies from HLS directory
        movies_dir = HLS_ROOT / 'movies'
        self.stdout.write(f"Scanning HLS directory: {movies_dir}")
        if movies_dir.exists():
            for d in movies_dir.iterdir():
                if d.is_dir():
                    self.stdout.write(f"Found folder: {d.name}")
                    m3u8_files = list(d.glob("*.m3u8"))
                    if m3u8_files:
                        m3u8_file = m3u8_files[0]
                        self.stdout.write(f"Found playlist: {m3u8_file.name}")
                        movie = None
                        for m in Movie.objects.all():
                            if Path(m.file_path).stem == d.name:
                                movie = m
                                break
                        
                        if not movie:
                            self.stdout.write(f"Missing movie found in HLS: {d.name}, rebuilding from TMDB...")
                            title, year = extract_title_year(d.name)
                            tmdb_data = fetch_tmdb_metadata(title, "MOVIE", year)
                            fake_path = f"/media/movies/{d.name}.mkv"
                            
                            poster_url = ""
                            if tmdb_data and tmdb_data.get("poster_path"):
                                poster_url = TMDB_IMAGE_BASE + tmdb_data["poster_path"]

                            movie = Movie(
                                title=tmdb_data.get("title", title) if tmdb_data else title,
                                description=tmdb_data.get("overview", "") if tmdb_data else "",
                                release_date=parse_date(tmdb_data.get("release_date")) if tmdb_data else None,
                                poster_url=poster_url,
                                tmdb_id=tmdb_data.get("id") if tmdb_data else 0,
                                file_path=fake_path,
                                is_converted=True,
                            )
                            movie.save()
                            self.stdout.write(self.style.SUCCESS(f"Re-created movie: {movie.title}"))
                        
                        # Fix flags
                        if not movie.is_converted or not movie.duration:
                            movie.is_converted = True
                            dur = get_duration(m3u8_file)
                            if dur:
                                movie.duration = dur
                            movie.save(update_fields=['is_converted', 'duration'])
                            ConversionTask.objects.filter(movie=movie).delete()
                            self.stdout.write(self.style.SUCCESS(f"Fixed flags and duration for {movie.title}"))
                    else:
                        self.stdout.write(self.style.ERROR(f"No .m3u8 file found in root of {d.name}"))
                        self.stdout.write("Directory contents:")
                        for child in d.iterdir():
                            self.stdout.write(f"  - {child.name}")
