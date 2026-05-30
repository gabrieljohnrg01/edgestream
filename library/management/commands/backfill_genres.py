import time
from django.core.management.base import BaseCommand
from library.models import Movie, Series, Genre
from library.tmdb import fetch_tmdb_metadata, get_genre_names

class Command(BaseCommand):
    help = "Backfill genres for existing movies and series using TMDB"

    def handle(self, *args, **options):
        self.stdout.write("Backfilling genres for Movies...")
        for movie in Movie.objects.all():
            if movie.genres.exists():
                continue
            
            metadata = fetch_tmdb_metadata(movie.title, "MOVIE")
            if metadata:
                genre_ids = metadata.get("genre_ids", [])
                genre_names = get_genre_names(genre_ids)
                if genre_names:
                    genres = []
                    for g_name in genre_names:
                        g, _ = Genre.objects.get_or_create(name=g_name)
                        genres.append(g)
                    movie.genres.set(genres)
                    self.stdout.write(self.style.SUCCESS(f"Added genres to {movie.title}: {', '.join(genre_names)}"))
            time.sleep(0.5)

        self.stdout.write("Backfilling genres for Series...")
        for series in Series.objects.all():
            if series.genres.exists():
                continue

            metadata = fetch_tmdb_metadata(series.title, "SERIES")
            if metadata:
                genre_ids = metadata.get("genre_ids", [])
                genre_names = get_genre_names(genre_ids)
                if genre_names:
                    genres = []
                    for g_name in genre_names:
                        g, _ = Genre.objects.get_or_create(name=g_name)
                        genres.append(g)
                    series.genres.set(genres)
                    self.stdout.write(self.style.SUCCESS(f"Added genres to {series.title}: {', '.join(genre_names)}"))
            time.sleep(0.5)
            
        self.stdout.write(self.style.SUCCESS("Backfill complete!"))
