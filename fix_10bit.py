import os
import subprocess
from pathlib import Path

# The base directories where the media is stored
hls_roots = [
    Path("media/hls/series/Georgie & Mandy's First Marriage/Season 1"),
    Path("media/hls/movies/Zootopia 2 (2025) [1080p] [WEBRip] [x265] [10bit] [5.1] [YTS.BZ]")
]

# The variants that contain video
variants = ["1080p", "720p", "480p", "144p"]

def main():
    print("Starting 10-bit to 8-bit In-Place Conversion...")
    
    for hls_root in hls_roots:
        if not hls_root.exists():
            print(f"Error: Could not find {hls_root}")
            continue

        for episode_dir in sorted(hls_root.iterdir()):
            if not episode_dir.is_dir():
                continue
                
            print(f"\n========================================")
            print(f"Processing: {episode_dir.name}")
            
            for var in variants:
                var_dir = episode_dir / var
                if not var_dir.exists():
                    continue
                
                m3u8_files = list(var_dir.glob("*.m3u8"))
                if not m3u8_files:
                    continue
                m3u8_file = m3u8_files[0]
                
                # Check if already 8-bit
                ts_files = list(var_dir.glob("*.ts"))
                if ts_files:
                    probe = subprocess.run(
                        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=pix_fmt", "-of", "default=noprint_wrappers=1:nokey=1", str(ts_files[0])],
                        capture_output=True, text=True
                    )
                    if "10" not in probe.stdout:
                        print(f"  -> {var} is already 8-bit. Skipping.")
                        continue
                
                print(f"  -> Fixing variant: {var} ...")
                tmp_m3u8 = var_dir / "tmp.m3u8"
                seg_pattern = str(var_dir / f"{m3u8_file.stem}_fix_%03d.ts")
                
                # Re-encode to 8-bit H.264
                args = [
                    "ffmpeg", "-y", "-i", str(m3u8_file),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                    "-an", "-sn", # audio and subtitles are handled separately
                    "-f", "hls", "-hls_time", "4", "-hls_list_size", "0",
                    "-hls_segment_filename", seg_pattern, str(tmp_m3u8)
                ]
                
                result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                if result.returncode != 0:
                    print(f"     [ERROR] FFmpeg failed for {var}.")
                    print(f"     [FFmpeg Output]: {result.stdout[-500:]}")
                    if tmp_m3u8.exists(): tmp_m3u8.unlink()
                    for orphan in var_dir.glob(f"{m3u8_file.stem}_fix_*.ts"):
                        orphan.unlink()
                    continue
                    
                # Cleanup old 10-bit .ts files
                for old_ts in var_dir.glob(f"{m3u8_file.stem}_[0-9][0-9][0-9].ts"):
                    old_ts.unlink()
                    
                # Rename new 8-bit .ts files back to original names
                for new_ts in var_dir.glob(f"{m3u8_file.stem}_fix_*.ts"):
                    final_name = new_ts.name.replace("_fix", "")
                    new_ts.rename(var_dir / final_name)
                    
                # Replace old m3u8 with the new fixed one
                m3u8_file.unlink()
                tmp_m3u8.rename(m3u8_file)
                
                # Clean up the internal segment names in the m3u8 file
                content = m3u8_file.read_text(encoding='utf-8')
                content = content.replace("_fix", "")
                m3u8_file.write_text(content, encoding='utf-8')
                
                print(f"     [OK] {var} successfully downgraded to 8-bit H.264.")

if __name__ == "__main__":
    main()
