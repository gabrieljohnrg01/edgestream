import os
from pathlib import Path

target_dir = Path("media/hls/series/Georgie & Mandy's First Marriage/Season 1/Georgie.and.Mandys.First.Marriage.S01E02.1080p.x265-ELiTE/1080p")

if not target_dir.exists():
    print(f"Directory not found: {target_dir}")
else:
    print(f"Directory found! Files inside:")
    for f in target_dir.iterdir():
        print(f" - {f.name} (Size: {f.stat().st_size} bytes)")
        
    print("\nReading m3u8 files...")
    for f in target_dir.glob("*.m3u8"):
        print(f"\n--- {f.name} ---")
        content = f.read_text(encoding='utf-8')
        print(content[:500]) # Print first 500 chars
