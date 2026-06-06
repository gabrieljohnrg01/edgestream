import os
import subprocess
from pathlib import Path

import imageio_ffmpeg
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from library.models import ConversionTask, Movie, Episode

MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", str(settings.MEDIA_ROOT)))
HLS_ROOT = Path(os.environ.get("HLS_ROOT", str(MEDIA_ROOT / "hls")))

VARIANTS = [
    ("1080p", "1920x1080", 5000000),
    ("720p", "1280x720", 2500000),
    ("480p", "854x480", 1000000),
    ("144p", "256x144", 400000),
]


class Command(BaseCommand):
    help = "Process queued HLS conversion tasks one by one."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=1,
            help="Number of conversion tasks to process in this run.",
        )
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Retry failed tasks as part of the queue.",
        )

    def handle(self, *args, **options):
        from django.utils import timezone
        import datetime
        
        # Recover tasks stuck due to power outage/crashes
        stuck_timeout = timezone.now() - datetime.timedelta(hours=2)
        stuck_tasks = ConversionTask.objects.filter(status=ConversionTask.STATUS_PROCESSING, updated_at__lt=stuck_timeout)
        stuck_count = stuck_tasks.count()
        if stuck_count > 0:
            self.stdout.write(self.style.WARNING(f"Found {stuck_count} stuck tasks. Resetting to QUEUED."))
            stuck_tasks.update(status=ConversionTask.STATUS_QUEUED, progress=0, updated_at=timezone.now())

        limit = options["limit"]
        retry_failed = options["retry_failed"]
        ffmpeg = self._find_ffmpeg()

        for _ in range(limit):
            task = self._get_next_task(retry_failed)
            if not task:
                self.stdout.write(self.style.SUCCESS("No queued conversion tasks available."))
                return
            self._process_task(task, ffmpeg)

    def _find_ffmpeg(self):
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return "ffmpeg"

    def _get_next_task(self, retry_failed):
        queued_tasks = ConversionTask.objects.filter(status=ConversionTask.STATUS_QUEUED)
        task = queued_tasks.order_by("created_at").first()
        if task:
            return task
        if retry_failed:
            return ConversionTask.objects.filter(status=ConversionTask.STATUS_FAILED).order_by("created_at").first()
        return None

    def _process_task(self, task, ffmpeg):
        task.status = ConversionTask.STATUS_PROCESSING
        task.progress = 0
        task.error_message = ""
        task.updated_at = timezone.now()
        task.save(update_fields=["status", "progress", "error_message", "updated_at"])

        media_path = self._resolve_media_path(task.file_path)
        if not media_path or not media_path.exists():
            task.status = ConversionTask.STATUS_FAILED
            task.error_message = f"Source file not found: {task.file_path}"
            task.save(update_fields=["status", "error_message", "updated_at"])
            self.stderr.write(task.error_message)
            return

        try:
            self._convert_to_hls(ffmpeg, media_path, task)
            self._delete_source_file(media_path)
            self._mark_converted(task)
            task.delete()
            self.stdout.write(self.style.SUCCESS(f"Converted and removed from queue: {task.file_path}"))
        except Exception as exc:
            task.status = ConversionTask.STATUS_FAILED
            task.error_message = str(exc)
            task.updated_at = timezone.now()
            task.save(update_fields=["status", "error_message", "updated_at"])
            self.stderr.write(f"Conversion failed for {task.file_path}: {exc}")

    def _resolve_media_path(self, file_path):
        if not file_path.startswith("/media/"):
            return None
        rel_path = file_path[len("/media/"):]
        return MEDIA_ROOT / rel_path

    def _convert_to_hls(self, ffmpeg, infile, task):
        from library.views import get_media_duration
        from .conversion_utils import (
            probe_streams, fuzzy_match_subtitles, download_subtitles_with_subliminal,
            extract_subtitles, convert_external_subtitles_to_vtt, generate_master_playlist_with_audio
        )
        import re
        duration_td = get_media_duration(infile)
        total_seconds = duration_td.total_seconds() if duration_td else 1

        rel_path = Path(str(infile).replace(str(MEDIA_ROOT) + os.sep, ""))
        variant_root = HLS_ROOT / rel_path.with_suffix("")
        variant_root.mkdir(parents=True, exist_ok=True)

        basename = infile.stem
        master_playlist = variant_root / f"{basename}.m3u8"
        
        # 1. Probe streams
        audio_streams, subtitle_streams = probe_streams(ffmpeg, infile)
        
        # 2. Subtitles
        # Check embedded
        extracted_vtts = extract_subtitles(ffmpeg, infile, subtitle_streams, variant_root)
        
        # Check external
        title = task.movie.title if task.movie else (task.episode.title or task.episode.season.series.title)
        year = task.movie.release_date.year if task.movie and task.movie.release_date else None
        ext_subs = fuzzy_match_subtitles(infile, title, year)
        
        if ext_subs:
            convert_external_subtitles_to_vtt(ffmpeg, ext_subs, variant_root)
        elif not extracted_vtts:
            # Download via subliminal using explicit title and year
            download_subtitles_with_subliminal(infile, title=title, year=year)
            # Re-check external
            new_ext_subs = fuzzy_match_subtitles(infile, title, year)
            if new_ext_subs:
                convert_external_subtitles_to_vtt(ffmpeg, new_ext_subs, variant_root)

        total_variants = len(VARIANTS) + len(audio_streams)
        current_step = 0

        # 3. Process video variants
        use_qsv = True
        
        for label, size, bandwidth in VARIANTS:
            variant_dir = variant_root / label
            variant_dir.mkdir(parents=True, exist_ok=True)
            variant_playlist = variant_dir / f"{basename}.m3u8"
            seg_template = str(variant_dir / f"{basename}_%03d.ts")
            width, height = size.split("x")
            filter_expr = (
                f"scale=w={width}:h={height}:force_original_aspect_ratio=decrease,"
                f"pad=ceil(iw/2)*2:ceil(ih/2)*2"
            )

            def build_args(encoder="h264_qsv"):
                # QSV hardware encoders expect nv12, software expects yuv420p
                pix_fmt = "nv12" if encoder == "h264_qsv" else "yuv420p"
                preset = "fast" if encoder == "h264_qsv" else "ultrafast"
                
                args = [
                    ffmpeg, "-y", "-i", str(infile),
                    "-c:v", encoder, "-pix_fmt", pix_fmt, "-preset", preset, "-vf", filter_expr,
                ]
                if audio_streams:
                    args.extend(["-an"]) # No audio in video variants
                else:
                    args.extend(["-c:a", "aac", "-b:a", "128k", "-ac", "2"])
                    
                args.extend([
                    "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
                    "-hls_segment_filename", seg_template, str(variant_playlist)
                ])
                return args

            # Attempt QSV Hardware Acceleration First
            if use_qsv:
                try:
                    self._run_ffmpeg_progress(build_args("h264_qsv"), current_step, total_variants, total_seconds, task, f"{label} (QSV)")
                except RuntimeError:
                    self.stdout.write(self.style.WARNING(f"\n[Hardware Alert] Intel QSV failed for {label}. Falling back to standard libx264 software encoding..."))
                    use_qsv = False # Disable QSV for the rest of this conversion
            
            # Fallback to Software Encoding
            if not use_qsv:
                self._run_ffmpeg_progress(build_args("libx264"), current_step, total_variants, total_seconds, task, f"{label} (libx264)")
                
            current_step += 1

        # 4. Process audio variants
        for i, aud in enumerate(audio_streams):
            lang = aud.get("lang", f"trk{i}")
            variant_dir = variant_root / f"audio_{i}_{lang}"
            variant_dir.mkdir(parents=True, exist_ok=True)
            variant_playlist = variant_dir / "playlist.m3u8"
            seg_template = str(variant_dir / "audio_%03d.ts")
            
            args = [
                ffmpeg, "-y", "-i", str(infile),
                "-map", aud["index"],
                "-c:a", "aac", "-b:a", "128k", "-ac", "2",
                "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
                "-hls_segment_filename", seg_template, str(variant_playlist)
            ]
            self._run_ffmpeg_progress(args, current_step, total_variants, total_seconds, task, f"Audio {lang}")
            current_step += 1

        # 5. Master Playlist
        generate_master_playlist_with_audio(master_playlist, VARIANTS, audio_streams, basename)

    def _run_ffmpeg_progress(self, args, current_step, total_variants, total_seconds, task, label):
        import re
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, universal_newlines=True)
        time_pattern = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d+)")
        duration_pattern = re.compile(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)")
        local_total_seconds = total_seconds
        
        for line in process.stdout:
            if local_total_seconds <= 1:
                d_match = duration_pattern.search(line)
                if d_match:
                    dh, dm, ds = d_match.groups()
                    local_total_seconds = int(dh) * 3600 + int(dm) * 60 + float(ds)
                    from django.utils import timezone
                    if task.movie and not task.movie.duration:
                        task.movie.duration = timezone.timedelta(seconds=local_total_seconds)
                        task.movie.save(update_fields=["duration"])
                    
            match = time_pattern.search(line)
            if match and local_total_seconds > 0:
                h, m, s = match.groups()
                current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                variant_progress = min(current_seconds / local_total_seconds, 1.0)
                overall_progress = int(((current_step + variant_progress) / total_variants) * 100)
                if overall_progress > task.progress:
                    from django.utils import timezone
                    task.progress = min(overall_progress, 99)
                    task.updated_at = timezone.now()
                    task.save(update_fields=["progress", "updated_at"])
        
        process.wait()
        if process.returncode != 0:
            raise RuntimeError(f"FFmpeg failed for {label}")

    def _delete_source_file(self, infile):
        if infile.exists():
            infile.unlink()

    def _mark_converted(self, task):
        if task.movie:
            task.movie.is_converted = True
            task.movie.save(update_fields=["is_converted"])
        if task.episode:
            task.episode.is_converted = True
            task.episode.save(update_fields=["is_converted"])
