#!/usr/bin/env python

import os
import subprocess
import glob
import re

# --- CONFIGURATION ---
SOURCE_FOLDER = "."  # Current folder
OUTPUT_FOLDER = "combined_output"
EXTENSION = ".mp3"
# ---------------------

def get_duration(file_path):
    """Get the duration of an audio file in seconds using ffprobe."""
    # We use ffprobe to get exact duration for accurate chapter markers
    cmd = [
        'ffprobe', 
        '-v', 'error', 
        '-show_entries', 'format=duration', 
        '-of', 'default=noprint_wrappers=1:nokey=1', 
        file_path
    ]
    try:
        # Check if ffprobe is installed
        output = subprocess.check_output(cmd).decode('utf-8').strip()
        return float(output)
    except FileNotFoundError:
        print("Error: FFmpeg/FFprobe not found. Please install FFmpeg and add it to your PATH.")
        exit(1)
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return 0.0

def create_ffmpeg_metadata(chapters, output_path):
    """Generates the metadata file required by FFmpeg to embed chapters."""
    content = [";FFMETADATA1"]
    for chap in chapters:
        content.append("[CHAPTER]")
        content.append("TIMEBASE=1/1000") # Timebase in milliseconds
        content.append(f"START={chap['start']}")
        content.append(f"END={chap['end']}")
        content.append(f"title={chap['title']}")
        content.append("") 

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(content))

def natural_sort_key(filename):
    """
    Sorts by the Chapter Number (the last part of the filename).
    Handles "1, 2, 10" correctly instead of "1, 10, 2".
    """
    name_no_ext = os.path.splitext(os.path.basename(filename))[0]
    parts = name_no_ext.rsplit(' ', 1)
    
    # If we successfully split into [Prefix, Chapter]
    if len(parts) == 2:
        chapter_part = parts[1]
        # If chapter is a number, return it as integer for sorting
        if chapter_part.isdigit():
            return int(chapter_part)
            
    # Fallback: standard string sort
    return filename

def process_group(prefix, files):
    print(f"Processing Book: '{prefix}' ({len(files)} chapters)...")
    
    # Sort files naturally (1, 2, 10) rather than ASCII (1, 10, 2)
    files.sort(key=natural_sort_key)
    
    concat_list_path = f"temp_list_{prefix}.txt"
    metadata_path = f"temp_meta_{prefix}.txt"
    # Clean output filename (remove potentially illegal chars for file system)
    safe_prefix = "".join([c for c in prefix if c.isalnum() or c in " ._-"]).strip()
    output_file = os.path.join(OUTPUT_FOLDER, f"{safe_prefix}.m4b")
    
    chapters = []
    current_time_ms = 0
    
    # 1. Build List and Calculate Times
    with open(concat_list_path, 'w', encoding='utf-8') as f_list:
        for file_path in files:
            # Escape single quotes for FFmpeg concat file
            safe_path = file_path.replace("'", "'\\''")
            f_list.write(f"file '{safe_path}'\n")
            
            duration_sec = get_duration(file_path)
            duration_ms = int(duration_sec * 1000)
            
            # Use the filename (without ext) as the Chapter Title
            chapter_title = os.path.splitext(os.path.basename(file_path))[0]
            
            chapters.append({
                'title': chapter_title,
                'start': current_time_ms,
                'end': current_time_ms + duration_ms
            })
            current_time_ms += duration_ms

    # 2. Create Metadata File
    create_ffmpeg_metadata(chapters, metadata_path)
    
    # 3. Run FFmpeg Concatenation
    # We use AAC codec for M4B to ensure compatibility.
    # Optimized for Voice: Mono, 64kbps
    cmd = [
        'ffmpeg',
        '-f', 'concat',
        '-safe', '0',
        '-i', concat_list_path,
        '-i', metadata_path,
        '-map_metadata', '1',
        '-map_chapters', '1',
        '-c:a', 'aac',     # AAC is standard for M4B
        '-b:a', '32k',     # 64k is sufficient for mono voice
        '-y',              # Overwrite existing
        output_file
    ]
    
    try:
        # Capture output to debug if it fails
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        print(f"-> Created: {output_file}")
    except subprocess.CalledProcessError as e:
        print(f"-> Failed to create {output_file}")
        # Print the error output from FFmpeg
        print(f"FFmpeg Error Output:\n{e.stdout.decode('utf-8', errors='replace')}")

    # Cleanup
    if os.path.exists(concat_list_path): os.remove(concat_list_path)
    if os.path.exists(metadata_path): os.remove(metadata_path)

def main():
    if not os.path.exists(OUTPUT_FOLDER):
        os.makedirs(OUTPUT_FOLDER)

    all_files = glob.glob(os.path.join(SOURCE_FOLDER, f"*{EXTENSION}"))
    
    # Group files
    groups = {}
    for f in all_files:
        filename = os.path.basename(f)
        name_no_ext = os.path.splitext(filename)[0]
        
        # Split starting from the RIGHT side, max 1 split.
        # "01 Book Name 01" -> ["01 Book Name", "01"]
        parts = name_no_ext.rsplit(' ', 1)
        
        if len(parts) == 2:
            prefix = parts[0] # The Book Number + Book Name
            if prefix not in groups:
                groups[prefix] = []
            groups[prefix].append(f)
        else:
            print(f"Skipping '{filename}' (Could not find a space to split Book Name and Chapter)")

    # Execute
    for prefix, files in groups.items():
        process_group(prefix, files)

if __name__ == "__main__":
    main()
