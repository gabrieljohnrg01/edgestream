import subprocess
import re
import os
import glob
from pathlib import Path

def probe_streams(ffmpeg, filepath):
    """
    Returns a tuple of (audio_streams, subtitle_streams) where each is a list of dicts:
    {"index": "0:1", "lang": "eng", "codec": "aac", "type": "audio"}
    """
    args = [ffmpeg, "-i", str(filepath)]
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore')
    _, stderr = process.communicate()
    
    audio_streams = []
    subtitle_streams = []
    
    # Parse Stream #0:1(eng): Audio: aac (LC)...
    for line in stderr.split('\n'):
        if "Stream #" in line:
            if "Audio:" in line:
                match = re.search(r"Stream #(\d+:\d+)(?:\[0x[0-9a-f]+\])?(?:\(([a-zA-Z]+)\))?: Audio: (\w+)", line)
                if match:
                    audio_streams.append({
                        "index": match.group(1),
                        "lang": match.group(2) or "und",
                        "codec": match.group(3)
                    })
            elif "Subtitle:" in line:
                match = re.search(r"Stream #(\d+:\d+)(?:\[0x[0-9a-f]+\])?(?:\(([a-zA-Z]+)\))?: Subtitle: (\w+)", line)
                if match:
                    subtitle_streams.append({
                        "index": match.group(1),
                        "lang": match.group(2) or "und",
                        "codec": match.group(3)
                    })
                    
    return audio_streams, subtitle_streams

def fuzzy_match_subtitles(infile, title, year=None, output_dir=None):
    """
    Scans the directory for .srt or .vtt files that roughly match the title.
    Returns a list of matched file paths.
    """
    directory = Path(output_dir) if output_dir else Path(infile).parent
    matched_subs = []
    
    if not directory.exists():
        return matched_subs
        
    title_clean = re.sub(r'[^a-zA-Z0-9]', '', title.lower()) if title else ""
    
    for sub_file in directory.glob("*"):
        if sub_file.suffix.lower() in [".srt", ".vtt"]:
            sub_name = sub_file.stem.lower()
            sub_clean = re.sub(r'[^a-zA-Z0-9]', '', sub_name)
            
            # Simple fuzzy logic: if title is in the sub filename, or if they match closely
            if title_clean and title_clean in sub_clean:
                # if year is provided, check if it's there too
                if year and str(year) in sub_name:
                    matched_subs.append(sub_file)
                elif not year:
                    matched_subs.append(sub_file)
                    
            # Or if it exact matches the video stem
            elif sub_file.stem == Path(infile).stem:
                matched_subs.append(sub_file)
                
    return list(set(matched_subs))

def download_subtitles_with_subliminal(video_path, title=None, year=None, season=None, episode=None, output_dir=None):
    """
    Tries to download English subtitles for the video using subliminal.
    Returns the path to the downloaded subtitle file, or None.
    """
    try:
        import subliminal
        from babelfish import Language
        
        if title and season is not None and episode is not None:
            # It's a TV Show Episode
            video = subliminal.video.Episode(str(video_path), title, season, episode, year=year)
        elif title:
            # It's a Movie
            video = subliminal.video.Movie(str(video_path), title, year=year)
        else:
            video = subliminal.Video.fromname(str(video_path))
            
        from django.conf import settings
        os_user = getattr(settings, 'OPENSUBTITLES_USERNAME', None)
        os_pass = getattr(settings, 'OPENSUBTITLES_PASSWORD', None)
        
        provider_configs = None
        if os_user and os_pass:
            provider_configs = {'opensubtitles': {'username': os_user, 'password': os_pass}}
            
        best_subs = subliminal.download_best_subtitles([video], {Language('eng')}, provider_configs=provider_configs)
        
        saved_paths = []
        out_dir = Path(output_dir) if output_dir else Path(video_path).parent
        
        # Ensure out_dir exists
        out_dir.mkdir(parents=True, exist_ok=True)
        
        for v, subs in best_subs.items():
            if subs:
                # Save it in the directory
                subliminal.save_subtitles(v, subs, directory=str(out_dir))
                # subliminal creates files like video.en.srt
                for sub in subs:
                    # subliminal doesn't return the exact path saved, we just glob for .srt
                    saved_paths.append(sub)
        
        if saved_paths:
            # We just return true, fuzzy matcher will pick it up
            return True
    except Exception as e:
        print("Subliminal error:", e)
        
    return False

def extract_subtitles(ffmpeg, infile, subtitle_streams, out_dir):
    """
    Extracts embedded subtitles into .vtt files in out_dir.
    Returns a list of generated .vtt paths.
    """
    out_paths = []
    for i, sub in enumerate(subtitle_streams):
        lang = sub.get("lang", f"trk{i}")
        out_path = Path(out_dir) / f"sub_{i}_{lang}.vtt"
        
        # ffmpeg -i in.mkv -map 0:s:0 out.vtt
        args = [
            ffmpeg, "-y", "-i", str(infile),
            "-map", sub["index"],
            str(out_path)
        ]
        subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        if out_path.exists() and out_path.stat().st_size > 0:
            out_paths.append(out_path)
            
    return out_paths

def convert_external_subtitles_to_vtt(ffmpeg, sub_paths, out_dir):
    """
    Converts .srt files to .vtt files in out_dir.
    """
    out_vtt_paths = []
    for i, sub_path in enumerate(sub_paths):
        if sub_path.suffix.lower() == ".vtt":
            # Just copy it
            import shutil
            out_path = Path(out_dir) / f"ext_sub_{i}.vtt"
            shutil.copy(sub_path, out_path)
            out_vtt_paths.append(out_path)
        else:
            out_path = Path(out_dir) / f"ext_sub_{i}.vtt"
            args = [
                ffmpeg, "-y", "-i", str(sub_path),
                str(out_path)
            ]
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if out_path.exists() and out_path.stat().st_size > 0:
                out_vtt_paths.append(out_path)
                
    return out_vtt_paths

def generate_master_playlist_with_audio(master_playlist_path, variants, audio_streams, basename):
    """
    Writes a custom master.m3u8 incorporating #EXT-X-MEDIA:TYPE=AUDIO and video variants.
    """
    with open(master_playlist_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n#EXT-X-VERSION:4\n")
        
        # Write audio streams
        # E.g. #EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",LANGUAGE="eng",NAME="English",DEFAULT=YES,URI="audio_eng/playlist.m3u8"
        for i, aud in enumerate(audio_streams):
            lang = aud.get("lang", f"trk{i}")
            if lang.lower().startswith("trk") or lang.lower() == "und":
                name = f"Track {i + 1}"
            else:
                name = f"Track {i + 1} ({lang.upper()})"
            is_default = "YES" if i == 0 else "NO"
            uri = f"audio_{i}_{lang}/playlist.m3u8"
            f.write(f'#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="audio",LANGUAGE="{lang}",NAME="{name}",DEFAULT={is_default},AUTOSELECT={is_default},URI="{uri}"\n')
            
        # Write video variants
        for label, size, bandwidth in variants:
            audio_attr = ',AUDIO="audio"' if audio_streams else ""
            f.write(f'#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},RESOLUTION={size}{audio_attr}\n')
            f.write(f"{label}/{basename}.m3u8\n")
