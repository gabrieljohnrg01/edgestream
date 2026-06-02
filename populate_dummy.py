import os
import django
from pathlib import Path
from django.utils import timezone

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mediaserver.settings")
django.setup()

from library.models import Movie, Series, Season, Episode

# Create Dummy Movie
movie, _ = Movie.objects.get_or_create(
    title="Dummy Movie: The Adventure",
    defaults={
        "description": "A fake movie to test the application UI and layout.",
        "tmdb_id": 1,
        "release_date": timezone.now().date(),
        "duration": timezone.timedelta(seconds=7200),
        "poster_url": "/static/library/logo.png",
        "backdrop_url": "/static/library/logo.png",
        "file_path": "/media/movies/dummy_movie/dummy_movie.mp4",
        "is_converted": True
    }
)

# Create Dummy Series
series, _ = Series.objects.get_or_create(
    title="Dummy Series",
    defaults={
        "description": "A fake TV show to test the React Native layout.",
        "tmdb_id": 2,
        "release_date": timezone.now().date(),
        "poster_url": "/static/library/logo.png",
        "backdrop_url": "/static/library/logo.png",
    }
)

season, _ = Season.objects.get_or_create(
    series=series,
    season_number=1,
    defaults={"poster_url": "/static/library/logo.png"}
)

episode, _ = Episode.objects.get_or_create(
    season=season,
    episode_number=1,
    defaults={
        "title": "Pilot (Dummy)",
        "description": "The first dummy episode.",
        "file_path": "/media/series/dummy_series/s01/e01.mp4",
        "is_converted": True
    }
)

# Create dummy .m3u8 files so the serializer generates HLS paths
from django.conf import settings
hls_root = Path(settings.MEDIA_ROOT) / "hls"

# Movie HLS
movie_dir = hls_root / "movies" / "dummy_movie"
movie_dir.mkdir(parents=True, exist_ok=True)
with open(movie_dir / "dummy_movie.m3u8", "w") as f:
    f.write("#EXTM3U\n")

# Episode HLS
ep_dir = hls_root / "series" / "dummy_series" / "s01"
ep_dir.mkdir(parents=True, exist_ok=True)
with open(ep_dir / "e01.m3u8", "w") as f:
    f.write("#EXTM3U\n")

print("Dummy Movie and Series successfully injected into database and HLS filesystem!")
