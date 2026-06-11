import os
import subprocess
from pathlib import Path
from datetime import datetime, time
from itertools import chain
from operator import attrgetter

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import IntegrityError
from django.db.models import Count, Q, Prefetch
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.decorators import login_required
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

from .models import Movie, Series, Season, Episode, MediaItem, ConversionTask, WatchlistItem, PlaybackProgress, Genre
from .tmdb import TMDB_IMAGE_BASE, clean_title, extract_title_year, fetch_tmdb_metadata, parse_date

def webview_login(request):
    token = request.GET.get('token')
    next_url = request.GET.get('next', '/')
    if token:
        try:
            jwt_auth = JWTAuthentication()
            validated_token = jwt_auth.get_validated_token(token)
            user = jwt_auth.get_user(validated_token)
            if user and user.is_active:
                login(request, user)
                return redirect(next_url)
        except (InvalidToken, TokenError):
            pass
    return redirect('login')

def account_select(request):
    return render(request, 'library/account_select.html')

def get_sunday_midnight():
    """Get the last Sunday at midnight (00:00) in timezone-aware format."""
    now = timezone.now()
    days_since_sunday = (now.weekday() + 1) % 7
    last_sunday = now - timezone.timedelta(days=days_since_sunday)
    last_sunday = last_sunday.replace(hour=0, minute=0, second=0, microsecond=0)
    return last_sunday


def should_reset_watch_count(item):
    """Check if item's watch count should be reset (if last reset was before this Sunday)."""
    last_sunday = get_sunday_midnight()
    return item.last_watch_reset < last_sunday


def get_converted_series_queryset():
    return Series.objects.filter(seasons__episodes__is_converted=True).distinct().prefetch_related("seasons")


def get_combined_recently_added(limit=20):
    """Get recently added movies and series combined."""
    movies = list(Movie.objects.filter(is_converted=True).order_by("-date_added")[:limit])
    series = list(get_converted_series_queryset().order_by("-date_added")[:limit])
    combined = sorted(
        chain(movies, series),
        key=attrgetter("date_added"),
        reverse=True
    )[:limit]
    return combined


def get_combined_top_items(limit=10):
    """Get top watched movies and series combined, resetting watch count if needed."""
    last_sunday = get_sunday_midnight()
    
    # Get all movies and reset if needed
    movies = Movie.objects.all()
    for movie in movies:
        if should_reset_watch_count(movie):
            movie.watch_count = 0
            movie.last_watch_reset = timezone.now()
            movie.save(update_fields=["watch_count", "last_watch_reset"])
    
    # Get all series and reset if needed
    series = Series.objects.all()
    for s in series:
        if should_reset_watch_count(s):
            s.watch_count = 0
            s.last_watch_reset = timezone.now()
            s.save(update_fields=["watch_count", "last_watch_reset"])
    
    # Get top items
    top_movies = list(Movie.objects.filter(is_converted=True).order_by("-watch_count", "-date_added")[:limit])
    top_series = list(get_converted_series_queryset().order_by("-watch_count", "-date_added")[:limit])
    combined = sorted(
        chain(top_movies, top_series),
        key=attrgetter("watch_count"),
        reverse=True
    )[:limit]
    return combined


def get_video_mime_type(file_path):
    ext = Path(file_path).suffix.lower()
    if ext == ".mp4":
        return "video/mp4"
    if ext == ".mkv":
        return "video/x-matroska"
    if ext == ".avi":
        return "video/x-msvideo"
    return "video/mp4"


def get_hls_playlist_path(file_path):
    """Convert media file path to HLS playlist path."""
    if not file_path.startswith("/media/"):
        return None

    rel_path = file_path[len("/media/"):]
    media_path = Path(rel_path)
    hls_dir = HLS_ROOT / media_path.with_suffix("")
    hls_playlist_name = media_path.with_suffix("").name + ".m3u8"
    hls_file = hls_dir / hls_playlist_name
    if hls_file.exists():
        import urllib.parse
        raw_path = (media_path.with_suffix("") / hls_playlist_name).as_posix()
        return f"/hls/{urllib.parse.quote(raw_path)}"
    return None

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(settings.MEDIA_ROOT)))
HLS_ROOT = Path(os.environ.get("HLS_ROOT", str(MEDIA_ROOT / "hls")))
MEDIA_FOLDERS = {
    "MOVIE": MEDIA_ROOT / "movies",
    "SERIES": MEDIA_ROOT / "series",
}


def get_media_duration(file_path):
    try:
        duration_path = Path(file_path)
        if file_path.startswith("/media/"):
            duration_path = MEDIA_ROOT / file_path[len("/media/"):]
        elif not duration_path.is_absolute():
            duration_path = MEDIA_ROOT / duration_path

        try:
            import imageio_ffmpeg
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError:
            ffmpeg_exe = "ffmpeg"
            
        import re
        result = subprocess.run([ffmpeg_exe, "-i", str(duration_path)], capture_output=True, text=True, timeout=20)
        match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", result.stderr)
        if match:
            h, m, s = match.groups()
            seconds = int(h) * 3600 + int(m) * 60 + float(s)
            return timezone.timedelta(seconds=seconds)
            
        # Fallback to ffprobe if ffmpeg didn't find it
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(duration_path),
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


def index(request):
    recently_added = get_combined_recently_added(limit=20)
    top_items = get_combined_top_items(limit=10)
    
    # Explicitly pull Top 10 weekly for movies and series
    top_movies_weekly = Movie.objects.filter(is_converted=True).order_by("-watch_count", "-date_added")[:10]
    top_series_weekly = get_converted_series_queryset().order_by("-watch_count", "-date_added")[:10]
    
    # The Featured Hero should show the newly added items
    featured = recently_added[0] if recently_added else None
    featured_items = recently_added[:4] if recently_added else []
    
    context = {
        "featured": featured,
        "featured_items": featured_items,
        "recently_added": recently_added,
        "top_items": top_items,
        "top_movies_weekly": top_movies_weekly,
        "top_series_weekly": top_series_weekly,
    }
    return render(request, "library/index.html", context)


def search(request):
    query = request.GET.get("q", "").strip()
    movies = Movie.objects.none()
    series = Series.objects.none()
    if query:
        movies = Movie.objects.filter(is_converted=True, title__icontains=query).order_by("title")
        series = get_converted_series_queryset().filter(title__icontains=query).order_by("title")
    context = {
        "query": query,
        "movies": movies,
        "series": series,
    }
    return render(request, "library/search_results.html", context)





def movies(request):
    featured_items = Movie.objects.filter(is_converted=True).order_by("-date_added")[:4]
    top_movies_weekly = Movie.objects.filter(is_converted=True).order_by("-watch_count", "-date_added")[:10]
    
    genre_rows = []
    
    recently_added = Movie.objects.filter(is_converted=True).order_by("-date_added")[:15]
    if recently_added.exists():
        genre_rows.append({"name": "Recently Added", "items": recently_added})
        
    genres = Genre.objects.filter(movie__is_converted=True).distinct().order_by("name")
    for genre in genres:
        genre_movies = Movie.objects.filter(is_converted=True, genres=genre).order_by("-watch_count")[:15]
        if genre_movies.exists():
            genre_rows.append({"name": genre.name, "items": genre_movies})
            
    context = {
        "featured_items": featured_items,
        "top_movies_weekly": top_movies_weekly,
        "genre_rows": genre_rows,
    }
    return render(request, "library/movies.html", context)


def series(request):
    featured_items = get_converted_series_queryset().order_by("-date_added")[:4]
    top_series_weekly = get_converted_series_queryset().order_by("-watch_count", "-date_added")[:10]
    
    genre_rows = []
    
    recently_added = get_converted_series_queryset().order_by("-date_added")[:15]
    if recently_added.exists():
        genre_rows.append({"name": "Recently Added", "items": recently_added})
        
    genres = Genre.objects.filter(series__seasons__episodes__is_converted=True).distinct().order_by("name")
    for genre in genres:
        genre_series = get_converted_series_queryset().filter(genres=genre).order_by("-watch_count")[:15]
        if genre_series.exists():
            genre_rows.append({"name": genre.name, "items": genre_series})
            
    context = {
        "featured_items": featured_items,
        "top_series_weekly": top_series_weekly,
        "genre_rows": genre_rows,
    }
    return render(request, "library/series.html", context)


def get_resume_episode(user, series_obj):
    if not user.is_authenticated:
        first_season = series_obj.seasons.filter(episodes__is_converted=True).order_by('season_number').first()
        if first_season:
            return first_season.episodes.filter(is_converted=True).order_by('episode_number').first()
        return None
        
    last_progress = PlaybackProgress.objects.filter(
        user=user, 
        episode__season__series=series_obj
    ).select_related('episode', 'episode__season').order_by('-last_watched').first()
    
    if not last_progress:
        first_season = series_obj.seasons.filter(episodes__is_converted=True).order_by('season_number').first()
        if first_season:
            return first_season.episodes.filter(is_converted=True).order_by('episode_number').first()
        return None
        
    if not last_progress.is_finished:
        return last_progress.episode
        
    current_ep = last_progress.episode
    next_ep = Episode.objects.filter(
        season=current_ep.season, 
        is_converted=True,
        episode_number__gt=current_ep.episode_number
    ).order_by('episode_number').first()
    
    if next_ep:
        return next_ep
        
    next_season = Season.objects.filter(
        series=series_obj,
        season_number__gt=current_ep.season.season_number
    ).order_by('season_number').first()
    
    if next_season:
        return next_season.episodes.filter(is_converted=True).order_by('episode_number').first()
        
    return current_ep

def series_detail(request, pk):
    from django.db.models import Prefetch
    series_obj = get_object_or_404(get_converted_series_queryset(), pk=pk)
    seasons = series_obj.seasons.filter(episodes__is_converted=True).distinct().prefetch_related(
        Prefetch("episodes", queryset=Episode.objects.filter(is_converted=True))
    )
    in_watchlist = False
    if request.user.is_authenticated:
        in_watchlist = WatchlistItem.objects.filter(user=request.user, series=series_obj).exists()
        
    resume_episode = get_resume_episode(request.user, series_obj)
    
    return render(request, "library/series_detail.html", {
        "series": series_obj,
        "seasons": seasons,
        "in_watchlist": in_watchlist,
        "resume_episode": resume_episode,
    })


def season_detail(request, series_pk, season_pk):
    series_obj = get_object_or_404(get_converted_series_queryset(), pk=series_pk)
    season = get_object_or_404(Season, pk=season_pk, series=series_obj)
    episodes = season.episodes.filter(is_converted=True)
    if not episodes.exists():
        raise Http404("Season not found")
    return render(request, "library/season_detail.html", {
        "series": series_obj,
        "season": season,
        "episodes": episodes,
    })


def get_hls_subtitles(file_path):
    import os
    from pathlib import Path
    from django.conf import settings
    MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(settings.MEDIA_ROOT)))
    HLS_ROOT = Path(os.environ.get("HLS_ROOT", str(MEDIA_ROOT / "hls")))
    
    raw_path = str(file_path)
    if raw_path.startswith('/media/'):
        raw_path = raw_path[7:]
    elif raw_path.startswith('media/'):
        raw_path = raw_path[6:]
    elif raw_path.startswith('\\media\\'):
        raw_path = raw_path[7:]
    elif raw_path.startswith('media\\'):
        raw_path = raw_path[6:]
        
    rel_path = Path(raw_path)
    variant_root = HLS_ROOT / rel_path.with_suffix("")
    
    subs = []
    if variant_root.exists():
        for vtt in variant_root.glob("*.vtt"):
            sub_rel = vtt.relative_to(MEDIA_ROOT).as_posix()
            
            # Simple label parsing
            label = vtt.stem.replace("sub_", "").replace("ext_", "External ")
            import urllib.parse
            subs.append({
                "url": f"/media/{urllib.parse.quote(sub_rel)}",
                "label": label.title(),
                "srclang": label[-3:] if len(label) >= 3 else "en"
            })
    return subs

def episode_playback(request, episode_pk):
    episode = get_object_or_404(Episode.objects.filter(is_converted=True), pk=episode_pk)
    season = episode.season
    series_obj = season.series
    
    # Increment watch count for series
    series_obj.watch_count += 1
    series_obj.save(update_fields=["watch_count"])
    
    # Get adjacent episodes for navigation
    prev_episode = episode.season.episodes.filter(is_converted=True, episode_number__lt=episode.episode_number).order_by("-episode_number").first()
    next_episode = episode.season.episodes.filter(is_converted=True, episode_number__gt=episode.episode_number).order_by("episode_number").first()
    
    hls_playlist = get_hls_playlist_path(episode.file_path)
    if not hls_playlist:
        raise Http404("Episode is still converting")
        
    saved_timestamp = 0
    if request.user.is_authenticated:
        progress = PlaybackProgress.objects.filter(user=request.user, episode=episode).first()
        if progress and not progress.is_finished:
            saved_timestamp = progress.timestamp

    return render(request, "library/episode_playback.html", {
        "episode": episode,
        "season": season,
        "series": series_obj,
        "prev_episode": prev_episode,
        "next_episode": next_episode,
        "hls_playlist": hls_playlist,
        "subtitles": get_hls_subtitles(episode.file_path),
        "fallback_file": episode.file_path,
        "fallback_type": get_video_mime_type(episode.file_path),
        "saved_timestamp": saved_timestamp,
    })


def movie_detail(request, pk):
    movie = get_object_or_404(Movie.objects.filter(is_converted=True), pk=pk)
    if not movie.duration:
        duration = get_media_duration(movie.file_path)
        if duration:
            movie.duration = duration
            movie.save(update_fields=["duration"])
    in_watchlist = False
    if request.user.is_authenticated:
        in_watchlist = WatchlistItem.objects.filter(user=request.user, movie=movie).exists()
    return render(request, "library/movie_detail.html", {
        "movie": movie,
        "in_watchlist": in_watchlist,
    })


def movie_playback(request, pk):
    movie = get_object_or_404(Movie.objects.filter(is_converted=True), pk=pk)
    
    # Increment watch count
    movie.watch_count += 1
    movie.save(update_fields=["watch_count"])
    
    hls_playlist = get_hls_playlist_path(movie.file_path)
    if not hls_playlist:
        raise Http404("Movie is still converting")
        
    saved_timestamp = 0
    if request.user.is_authenticated:
        progress = PlaybackProgress.objects.filter(user=request.user, movie=movie).first()
        if progress and not progress.is_finished:
            saved_timestamp = progress.timestamp

    return render(request, "library/movie_playback.html", {
        "movie": movie,
        "hls_playlist": hls_playlist,
        "subtitles": get_hls_subtitles(movie.file_path),
        "fallback_file": movie.file_path,
        "fallback_type": get_video_mime_type(movie.file_path),
        "saved_timestamp": saved_timestamp,
    })



def queue_dashboard(request):
    tasks = ConversionTask.objects.order_by("status", "created_at")
    counts = {
        "queued": ConversionTask.objects.filter(status=ConversionTask.STATUS_QUEUED).count(),
        "processing": ConversionTask.objects.filter(status=ConversionTask.STATUS_PROCESSING).count(),
        "completed": ConversionTask.objects.filter(status=ConversionTask.STATUS_COMPLETED).count(),
        "failed": ConversionTask.objects.filter(status=ConversionTask.STATUS_FAILED).count(),
    }
    return render(request, "library/queue_dashboard.html", {
        "tasks": tasks,
        "counts": counts,
    })


def queue_status_api(request):
    tasks = ConversionTask.objects.all().order_by("-created_at")[:50]
    tasks_data = []
    for task in tasks:
        title = "Unknown"
        if task.movie:
            title = task.movie.title
        elif task.episode:
            title = f"Episode: {task.episode.season.series.title} S{task.episode.season.season_number}E{task.episode.episode_number}"
        
        tasks_data.append({
            "id": task.id,
            "title": title,
            "file_path": task.file_name,
            "status": task.status,
            "progress": task.progress,
            "error_message": task.error_message,
            "updated_at": task.updated_at.strftime("%Y-%m-%d %H:%M"),
        })
    return JsonResponse({"status": "success", "tasks": tasks_data})


def register_view(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("index")
    else:
        form = UserCreationForm()
    return render(request, "library/register.html", {"form": form})


def login_view(request):
    if request.method == "POST":
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            return redirect("index")
    else:
        form = AuthenticationForm()
    return render(request, "library/login.html", {"form": form})


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def watchlist_view(request):
    items = WatchlistItem.objects.filter(user=request.user)
    return render(request, "library/watchlist.html", {"items": items})


@login_required
def api_toggle_watchlist(request):
    if request.method == "POST":
        try:
            import json
            data = json.loads(request.body)
            item_type = data.get("type")
            item_id = data.get("id")
            if item_type == "movie":
                movie = Movie.objects.get(pk=item_id)
                item, created = WatchlistItem.objects.get_or_create(user=request.user, movie=movie)
                if not created:
                    item.delete()
                return JsonResponse({"status": "success", "added": created})
            elif item_type == "series":
                series = Series.objects.get(pk=item_id)
                item, created = WatchlistItem.objects.get_or_create(user=request.user, series=series)
                if not created:
                    item.delete()
                return JsonResponse({"status": "success", "added": created})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})
    return JsonResponse({"status": "error"})


@login_required
def api_update_progress(request):
    if request.method == "POST":
        try:
            import json
            data = json.loads(request.body)
            item_type = data.get("type")
            item_id = data.get("id")
            timestamp = data.get("timestamp")
            is_finished = data.get("is_finished", False)

            if item_type == "movie":
                movie = Movie.objects.get(pk=item_id)
                progress, _ = PlaybackProgress.objects.get_or_create(user=request.user, movie=movie)
                progress.timestamp = timestamp
                progress.is_finished = is_finished
                progress.save()
                return JsonResponse({"status": "success"})
            elif item_type == "episode":
                episode = Episode.objects.get(pk=item_id)
                progress, _ = PlaybackProgress.objects.get_or_create(user=request.user, episode=episode)
                progress.timestamp = timestamp
                progress.is_finished = is_finished
                progress.save()
                return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})
    return JsonResponse({"status": "error"})

@login_required
def api_clear_queue(request):
    if request.method == "POST":
        try:
            ConversionTask.objects.filter(status__in=["COMPLETED", "FAILED"]).delete()
            return JsonResponse({"status": "success"})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})
    return JsonResponse({"status": "error"}, status=400)

@login_required
def api_playback_progress(request):
    if request.method != "POST":
        return JsonResponse({"error": "Method not allowed"}, status=405)
    
    try:
        import json
        data = json.loads(request.body)
        media_type = data.get("type")
        item_id = data.get("id")
        progress = data.get("progress")
        duration = data.get("duration")
        
        if not all([media_type, item_id, progress is not None, duration is not None]):
            return JsonResponse({"error": "Missing parameters"}, status=400)
            
        try:
            progress = float(progress)
            duration = float(duration)
        except ValueError:
            return JsonResponse({"error": "Invalid progress or duration"}, status=400)
            
        progress_obj = None
        if media_type == "movie":
            movie = get_object_or_404(Movie, pk=item_id)
            progress_obj, _ = PlaybackProgress.objects.get_or_create(
                user=request.user, movie=movie,
                defaults={"progress": progress, "duration": duration}
            )
        elif media_type == "episode":
            episode = get_object_or_404(Episode, pk=item_id)
            progress_obj, _ = PlaybackProgress.objects.get_or_create(
                user=request.user, episode=episode,
                defaults={"progress": progress, "duration": duration}
            )
        else:
            return JsonResponse({"error": "Invalid media type"}, status=400)
            
        progress_obj.progress = progress
        progress_obj.duration = duration
        progress_obj.save()
        
        return JsonResponse({"status": "success"})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.contrib import messages
from .models import UserProfile

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def api_my_profile(request):
    try:
        profile = request.user.profile
    except Exception:
        profile = UserProfile.objects.create(user=request.user)
        
    if request.method == 'POST':
        theme = request.data.get('theme') or request.POST.get('theme')
        avatar = request.FILES.get('avatar')
        
        if theme:
            profile.theme = theme
        if avatar:
            profile.avatar = avatar
            
        profile.save()

    avatar_url = profile.avatar.url if profile.avatar else None
    theme = profile.theme
        
    return JsonResponse({
        'username': request.user.username,
        'avatar': avatar_url,
        'theme': theme
    })

@login_required
def settings_view(request):
    try:
        profile = request.user.profile
    except Exception:
        profile = UserProfile.objects.create(user=request.user)

    if request.method == 'POST':
        if 'update_profile' in request.POST:
            theme = request.POST.get('theme', 'default')
            avatar = request.FILES.get('avatar')
            
            profile.theme = theme
            if avatar:
                profile.avatar = avatar
            profile.save()
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                from django.http import JsonResponse
                return JsonResponse({
                    'status': 'success',
                    'theme': profile.theme,
                    'avatar': profile.avatar.url if profile.avatar else None
                })
            return redirect('settings')
            
        elif 'update_password' in request.POST:
            form = PasswordChangeForm(request.user, request.POST)
            if form.is_valid():
                user = form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Your password was successfully updated!')
                return redirect('settings')
            else:
                messages.error(request, 'Please correct the error below.')
    else:
        form = PasswordChangeForm(request.user)
        
    for field in form.fields.values():
        if 'autofocus' in field.widget.attrs:
            del field.widget.attrs['autofocus']
            
    return render(request, 'library/settings.html', {'form': form, 'profile': profile})
