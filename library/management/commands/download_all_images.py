from django.core.management.base import BaseCommand
from library.models import Movie, Series, Season, Episode
from library.tmdb import download_tmdb_image

class Command(BaseCommand):
    help = "Downloads all TMDB images currently hotlinked in the database and updates URLs."

    def handle(self, *args, **options):
        self.stdout.write("Downloading Movie images...")
        for movie in Movie.objects.all():
            updated = False
            if movie.poster_url and movie.poster_url.startswith("http"):
                movie.poster_url = download_tmdb_image(movie.poster_url, "posters")
                updated = True
            if movie.backdrop_url and movie.backdrop_url.startswith("http"):
                movie.backdrop_url = download_tmdb_image(movie.backdrop_url, "backdrops")
                updated = True
            if updated:
                movie.save(update_fields=["poster_url", "backdrop_url"])
                self.stdout.write(f"Updated Movie: {movie.title}")
                
        self.stdout.write("Downloading Series images...")
        for series in Series.objects.all():
            updated = False
            if series.poster_url and series.poster_url.startswith("http"):
                series.poster_url = download_tmdb_image(series.poster_url, "posters")
                updated = True
            if series.backdrop_url and series.backdrop_url.startswith("http"):
                series.backdrop_url = download_tmdb_image(series.backdrop_url, "backdrops")
                updated = True
            if updated:
                series.save(update_fields=["poster_url", "backdrop_url"])
                self.stdout.write(f"Updated Series: {series.title}")
                
        self.stdout.write("Downloading Season images...")
        for season in Season.objects.all():
            if season.poster_url and season.poster_url.startswith("http"):
                season.poster_url = download_tmdb_image(season.poster_url, "posters")
                season.save(update_fields=["poster_url"])
                self.stdout.write(f"Updated Season: {season.series.title} S{season.season_number}")
                
        self.stdout.write("Downloading Episode images...")
        for ep in Episode.objects.all():
            if ep.still_url and ep.still_url.startswith("http"):
                ep.still_url = download_tmdb_image(ep.still_url, "stills")
                ep.save(update_fields=["still_url"])
                self.stdout.write(f"Updated Episode: S{ep.season.season_number}E{ep.episode_number}")
                
        self.stdout.write(self.style.SUCCESS("Finished downloading all TMDB images!"))
