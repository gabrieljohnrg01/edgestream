import mimetypes
import posixpath
import re
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotModified, StreamingHttpResponse
from django.urls import include, path
from django.utils._os import safe_join
from django.utils.http import http_date


def serve_media(request, path, document_root=None):
    path = posixpath.normpath(path).lstrip("/")
    fullpath = Path(safe_join(document_root, path))
    if fullpath.is_dir() or not fullpath.exists():
        raise Http404("Media file not found")

    statobj = fullpath.stat()
    if request.META.get("HTTP_IF_MODIFIED_SINCE"):
        from django.views.static import was_modified_since

        if not was_modified_since(request.META.get("HTTP_IF_MODIFIED_SINCE"), statobj.st_mtime):
            return HttpResponseNotModified()

    content_type, encoding = mimetypes.guess_type(str(fullpath))
    content_type = content_type or "application/octet-stream"
    size = statobj.st_size
    range_header = request.META.get("HTTP_RANGE", "")
    range_match = re.match(r"bytes=(\d*)-(\d*)", range_header)

    def file_stream(start=0, length=None):
        with open(fullpath, "rb") as f:
            f.seek(start)
            remaining = length
            chunk_size = 8192
            while remaining is None or remaining > 0:
                read_size = chunk_size if remaining is None else min(chunk_size, remaining)
                chunk = f.read(read_size)
                if not chunk:
                    break
                yield chunk
                if remaining is not None:
                    remaining -= len(chunk)

    response = None
    if range_match:
        start_str, end_str = range_match.groups()
        if start_str:
            start = int(start_str)
            end = int(end_str) if end_str else size - 1
        else:
            suffix = int(end_str) if end_str else 0
            start = max(size - suffix, 0)
            end = size - 1

        if start >= size or end >= size or start > end:
            response = HttpResponse(status=416)
            response.headers["Content-Range"] = f"bytes */{size}"
        else:
            length = end - start + 1
            response = StreamingHttpResponse(
                file_stream(start, length),
                status=206,
                content_type=content_type,
            )
            response.headers["Content-Range"] = f"bytes {start}-{end}/{size}"
            response.headers["Content-Length"] = str(length)
    else:
        response = FileResponse(open(fullpath, "rb"), content_type=content_type)
        response.headers["Content-Length"] = str(size)

    response.headers["Accept-Ranges"] = "bytes"
    response.headers["Last-Modified"] = http_date(statobj.st_mtime)
    if encoding:
        response.headers["Content-Encoding"] = encoding
    return response


from rest_framework import routers
from library.api import MovieViewSet, SeriesViewSet, SeasonViewSet, EpisodeViewSet
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

router = routers.DefaultRouter()
router.register(r'movies', MovieViewSet, basename='movie')
router.register(r'series', SeriesViewSet, basename='series')
router.register(r'seasons', SeasonViewSet, basename='season')
router.register(r'episodes', EpisodeViewSet, basename='episode')

urlpatterns = [
    path("cd8e67206a28a6444351.txt", lambda request: HttpResponse("3e22655f2b541b1ac9cb", content_type="text/plain")),
    path("api/token/", TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path("api/token/refresh/", TokenRefreshView.as_view(), name='token_refresh'),
    path("api/", include(router.urls)),
    path("", include("library.urls")),
]

if settings.DEBUG:
    urlpatterns += [
        path("media/<path:path>", serve_media, {"document_root": settings.MEDIA_ROOT}),
        path("hls/<path:path>", serve_media, {"document_root": getattr(settings, 'HLS_ROOT', settings.MEDIA_ROOT / "hls")}),
    ]
