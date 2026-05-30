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
                    # Find all m3u8 files recursively
                    m3u8_files = list(d.rglob("*.m3u8"))
                    master_playlist = None
                    
                    # Find the master playlist (it contains EXT-X-STREAM-INF)
                    for m3u8 in m3u8_files:
                        try:
                            content = m3u8.read_text(encoding='utf-8')
                            if "EXT-X-STREAM-INF" in content:
                                master_playlist = m3u8
                                break
                        except Exception:
                            pass
                    
                    # Fallback to the shortest path if no master playlist tag found
                    if not master_playlist and m3u8_files:
                        master_playlist = sorted(m3u8_files, key=lambda p: len(p.parts))[0]

                    if master_playlist:
                        self.stdout.write(f"Found master playlist: {master_playlist.relative_to(HLS_ROOT)}")
                        
                        # Reconstruct the original file_path that views.py expects
                        # HLS path: movies/Folder/Subfolder/Subfolder.m3u8
                        # Original path: /media/movies/Folder/Subfolder.mkv
                        rel_hls_dir = master_playlist.parent.relative_to(HLS_ROOT) # e.g. movies/Folder/Subfolder
                        fake_path = f"/media/{rel_hls_dir}.mkv"
                        
                        movie = Movie.objects.filter(file_path=fake_path).first()
                        
                        if not movie:
                            # Try matching by title if file_path changed
                            title_search = extract_title_year(master_playlist.parent.name)[0]
                            movie = Movie.objects.filter(title__icontains=title_search).first()
                            
                        if not movie:
                            self.stdout.write(f"Missing movie found in HLS: {master_playlist.parent.name}, rebuilding from TMDB...")
                            title, year = extract_title_year(master_playlist.parent.name)
                            
                            # If it's a nested folder, maybe the parent folder has a cleaner name for TMDB
                            if d.name != master_playlist.parent.name:
                                parent_title, parent_year = extract_title_year(d.name)
                                # Only use parent title if it looks valid
                                if parent_title and len(parent_title) > 2:
                                    title, year = parent_title, parent_year
                                    
                            tmdb_data = fetch_tmdb_metadata(title, "MOVIE", year)
                            
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
                            dur = get_duration(master_playlist)
                            if dur:
                                movie.duration = dur
                            # Fix file path if it differs
                            if movie.file_path != fake_path:
                                movie.file_path = fake_path
                            movie.save(update_fields=['is_converted', 'duration', 'file_path'])
                            ConversionTask.objects.filter(movie=movie).delete()
                            self.stdout.write(self.style.SUCCESS(f"Fixed flags and duration for {movie.title}"))
                    else:
                        self.stdout.write(self.style.ERROR(f"No .m3u8 file found in {d.name}"))
