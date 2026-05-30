import os
import re
import subprocess
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from library.models import Movie, Series, Season, Episode, ConversionTask
from library.tmdb import (
    TMDB_IMAGE_BASE,
    clean_title,
    extract_title_year,
    fetch_tmdb_metadata,
    fetch_season_details,
    fetch_episode_details,
    parse_date,
)

MEDIA_ROOT = os.environ.get("MEDIA_ROOT", str(settings.MEDIA_ROOT))
MEDIA_FOLDERS = {
    "movies": os.path.join(MEDIA_ROOT, "movies"),
    "series": os.path.join(MEDIA_ROOT, "series"),
}

HLS_ROOT = Path(os.environ.get("HLS_ROOT", str(Path(MEDIA_ROOT) / "hls")))


def has_hls_playlist(file_path):
    if not file_path.startswith("/media/"):
        return False
    rel_path = Path(file_path[len("/media/"):])
    hls_dir = HLS_ROOT / rel_path.with_suffix("")
    playlist_name = rel_path.with_suffix("").name + ".m3u8"
    return (hls_dir / playlist_name).exists()


def get_media_duration(path):
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
        seconds = float(result.stdout.strip())
        return timezone.timedelta(seconds=seconds)
    except Exception:
        return None


def extract_season_episode(filename):
    try:
        from guessit import guessit
        guess = guessit(filename)
        season = guess.get("season")
        episode = guess.get("episode")
        
        if isinstance(episode, list):
            episode = episode[0]
            
        if season is not None and episode is not None:
            return int(season), int(episode)
    except ImportError:
        pass

    match = re.search(r"[Ss](\d{1,2})[Ee](\d{1,2})", filename)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


class Command(BaseCommand):
    help = "Scan local media folders and index movies and series."

    def handle(self, *args, **options):
        self.scan_movies()
        self.scan_series()

    def scan_movies(self):
        movies_dir = MEDIA_FOLDERS["movies"]
        if not os.path.isdir(movies_dir):
            self.stdout.write(self.style.WARNING(f"Skipping {movies_dir}: directory does not exist."))
            return

        for root, _, files in os.walk(movies_dir):
            for filename in sorted(files):
                if not filename.lower().endswith((".mp4", ".avi")):
                    continue

                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, MEDIA_ROOT).replace(os.sep, "/")
                file_path = f"/media/{rel_path}"

                title_guess, year_guess = extract_title_year(filename)
                metadata = fetch_tmdb_metadata(title_guess, "MOVIE", year_guess)
                if not metadata:
                    self.stdout.write(self.style.WARNING(f"No TMDB metadata for '{filename}'."))
                    continue

                poster_path = metadata.get("poster_path") or ""
                poster_url = f"{TMDB_IMAGE_BASE}{poster_path}" if poster_path else ""
                description = metadata.get("overview", "")
                release_date = parse_date(metadata.get("release_date"))
                tmdb_id = metadata.get("id") or 0
                duration = get_media_duration(full_path)

                movie, created = Movie.objects.update_or_create(
                    file_path=file_path,
                    defaults={
                        "title": title_guess or filename,
                        "tmdb_id": tmdb_id,
                        "description": description,
                        "poster_url": poster_url,
                        "release_date": release_date,
                        "duration": duration,
                        "date_added": timezone.now(),
                        "is_converted": has_hls_playlist(file_path),
                    },
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Added MOVIE: {title_guess}"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"Updated MOVIE: {title_guess}"))

                if not movie.is_converted and not ConversionTask.objects.filter(file_path=file_path, status__in=[ConversionTask.STATUS_QUEUED, ConversionTask.STATUS_PROCESSING]).exists():
                    ConversionTask.objects.create(
                        file_path=file_path,
                        movie=movie,
                        status=ConversionTask.STATUS_QUEUED,
                    )

    def scan_series(self):
        series_dir = MEDIA_FOLDERS["series"]
        if not os.path.isdir(series_dir):
            self.stdout.write(self.style.WARNING(f"Skipping {series_dir}: directory does not exist."))
            return

        for root, _, files in os.walk(series_dir):
            for filename in sorted(files):
                if not filename.lower().endswith((".mp4", ".avi")):
                    continue

                season_num, episode_num = extract_season_episode(filename)
                if season_num is None or episode_num is None:
                    self.stdout.write(self.style.WARNING(f"Could not parse S/E from '{filename}'."))
                    continue

                full_path = os.path.join(root, filename)
                rel_path = os.path.relpath(full_path, MEDIA_ROOT).replace(os.sep, "/")
                file_path = f"/media/{rel_path}"

                if Episode.objects.filter(file_path=file_path).exists():
                    continue

                title_guess = clean_title(filename)
                metadata = fetch_tmdb_metadata(title_guess, "SERIES")
                if not metadata:
                    self.stdout.write(self.style.WARNING(f"No TMDB metadata for '{filename}'."))
                    continue

                series_title = metadata.get("name") or title_guess
                tmdb_id = metadata.get("id") or 0
                series, created = Series.objects.update_or_create(
                    title=series_title,
                    defaults={
                        "tmdb_id": tmdb_id,
                        "description": metadata.get("overview", ""),
                        "poster_url": f"{TMDB_IMAGE_BASE}{metadata.get('poster_path')}" if metadata.get("poster_path") else "",
                        "release_date": parse_date(metadata.get("first_air_date")),
                    },
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Added SERIES: {series_title}"))
                else:
                    self.stdout.write(self.style.SUCCESS(f"Updated SERIES: {series_title}"))

                # Fetch season details for poster
                season_details = fetch_season_details(tmdb_id, season_num)
                season_poster = ""
                if season_details and season_details.get("poster_path"):
                    season_poster = f"{TMDB_IMAGE_BASE}{season_details.get('poster_path')}"

                season, _ = Season.objects.update_or_create(
                    series=series,
                    season_number=season_num,
                    defaults={"poster_url": season_poster},
                )

                if season_poster and season.poster_url != season_poster:
                    season.poster_url = season_poster
                    season.save(update_fields=["poster_url"])

                # Fetch episode details
                episode_details = fetch_episode_details(tmdb_id, season_num, episode_num)
                ep_title = episode_details.get("name", "") if episode_details else ""
                ep_description = episode_details.get("overview", "") if episode_details else ""
                ep_still = ""
                if episode_details and episode_details.get("still_path"):
                    ep_still = f"{TMDB_IMAGE_BASE}{episode_details.get('still_path')}"

                episode, created = Episode.objects.update_or_create(
                    season=season,
                    episode_number=episode_num,
                    defaults={
                        "file_path": file_path,
                        "title": ep_title,
                        "description": ep_description,
                        "still_url": ep_still,
                        "is_converted": has_hls_playlist(file_path),
                    },
                )

                if created:
                    self.stdout.write(
                        self.style.SUCCESS(f"Added {series_title} S{season_num:02d}E{episode_num:02d}: {ep_title}")
                    )
                else:
                    self.stdout.write(
                        self.style.SUCCESS(f"Updated {series_title} S{season_num:02d}E{episode_num:02d}: {ep_title}")
                    )

                if not episode.is_converted and not ConversionTask.objects.filter(file_path=file_path, status__in=[ConversionTask.STATUS_QUEUED, ConversionTask.STATUS_PROCESSING]).exists():
                    ConversionTask.objects.create(
                        file_path=file_path,
                        episode=episode,
                        status=ConversionTask.STATUS_QUEUED,
                    )
