#!/usr/bin/env python3
"""
Create animated GIFs and videos from waterfall plots for all states.
Each animation cycles through all 21 filter waterfall plots.

Usage:
    python create_waterfall_animations.py [DATE]
    
    DATE format: YYYYMMDD (e.g., 20251102 for Nov 2, 2025)
    If no date provided, defaults to 20251102
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import glob
import subprocess
import numpy as np
from PIL import Image

def get_date_and_day(date_str):
    """Extract day number from date string (YYYYMMDD)."""
    if not date_str or len(date_str) != 8:
        raise ValueError("Date must be in format YYYYMMDD")
    
    day = str(int(date_str[6:8]))  # Remove leading zero
    return date_str, day

def find_waterfall_images(plots_dir, state):
    """
    Find all waterfall images for a given state, sorted by filter number.
    Returns list of (filter_num, image_path) tuples.
    """
    pattern = f"{plots_dir}/**/20*_state_{state}_filter_*_waterfall.png"
    images = glob.glob(pattern, recursive=True)
    
    if not images:
        return []
    
    # Extract filter number from filename and sort
    filter_images = []
    for img_path in images:
        # Extract filter number from filename (e.g., "filter_10_waterfall.png" -> 10)
        filename = os.path.basename(img_path)
        try:
            filter_num = int(filename.split("filter_")[-1].split("_waterfall")[0])
            filter_images.append((filter_num, img_path))
        except (ValueError, IndexError):
            print(f"Warning: Could not parse filter number from {filename}")
            continue
    
    # Sort by filter number
    filter_images.sort(key=lambda x: x[0])
    return filter_images

def create_gif(images_list, output_path, duration=1000, loop=0):
    """
    Create an animated GIF from a list of images.
    
    Args:
        images_list: List of image file paths
        output_path: Output GIF file path
        duration: Duration per frame in milliseconds
        loop: 0 = infinite loop
    """
    if not images_list:
        print(f"No images to create GIF: {output_path}")
        return False
    
    print(f"  Loading {len(images_list)} images for GIF...")
    pil_images = []
    for img_path in images_list:
        try:
            img = Image.open(img_path)
            pil_images.append(img)
        except Exception as e:
            print(f"    Error loading {img_path}: {e}")
            continue
    
    if not pil_images:
        print(f"  Failed to load any images for GIF")
        return False
    
    print(f"  Creating GIF with {len(pil_images)} frames...")
    try:
        pil_images[0].save(
            output_path,
            save_all=True,
            append_images=pil_images[1:],
            duration=duration,
            loop=loop,
            optimize=False
        )
        print(f"  ✓ GIF saved: {output_path}")
        return True
    except Exception as e:
        print(f"  ✗ Error creating GIF: {e}")
        return False

def create_video(images_list, output_path, fps=1):
    """
    Create an MP4 video from a list of images using ffmpeg.
    
    Args:
        images_list: List of image file paths
        output_path: Output MP4 file path
        fps: Frames per second
    """
    if not images_list:
        print(f"No images to create video: {output_path}")
        return False
    
    print(f"  Creating video with {len(images_list)} frames at {fps} fps...")
    
    # Create a temporary text file with list of images for ffmpeg
    temp_list = output_path.replace(".mp4", "_filelist.txt")
    try:
        with open(temp_list, "w") as f:
            for img_path in images_list:
                # Escape single quotes in path
                escaped_path = img_path.replace("'", "'\\''")
                f.write(f"file '{escaped_path}'\n")
        
        # Run ffmpeg to create video
        cmd = [
            "ffmpeg",
            "-f", "concat",
            "-safe", "0",
            "-i", temp_list,
            "-framerate", str(fps),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-y",  # Overwrite output
            output_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        # Clean up temp file
        if os.path.exists(temp_list):
            os.remove(temp_list)
        
        if result.returncode == 0:
            print(f"  ✓ Video saved: {output_path}")
            return True
        else:
            print(f"  ✗ Error creating video: {result.stderr}")
            return False
    except Exception as e:
        print(f"  ✗ Error: {e}")
        if os.path.exists(temp_list):
            os.remove(temp_list)
        return False

def main():
    # Parse arguments
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        date_str = "20251102"
    
    try:
        date_str, day = get_date_and_day(date_str)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    
    # Setup paths
    plots_base = f"/Users/abdullaalhosani/Projects/highz/plots/Nov{day}"
    
    if not os.path.isdir(plots_base):
        print(f"Error: Plots directory not found: {plots_base}")
        sys.exit(1)
    
    # States to process
    states = ["0", "1", "2", "3", "4", "5", "6", "7", "1_OC"]
    
    print(f"\nCreating waterfall animations for {date_str} (Nov {day})")
    print(f"Plots directory: {plots_base}")
    print(f"States to process: {', '.join(states)}\n")
    
    for state in states:
        print(f"Processing State {state}...")
        
        # Find all waterfall images for this state
        filter_images = find_waterfall_images(plots_base, state)
        
        if not filter_images:
            print(f"  ✗ No waterfall images found for state {state}")
            continue
        
        # Extract just the paths (sorted by filter number)
        image_paths = [img_path for _, img_path in filter_images]
        
        print(f"  Found {len(image_paths)} filter waterfall plots")
        print(f"  Filters: {', '.join(str(f) for f, _ in filter_images)}")
        
        # Create GIF (1 second per frame)
        gif_path = os.path.join(plots_base, f"state_{state}_waterfall_animation.gif")
        create_gif(image_paths, gif_path, duration=1000)
        
        # Create video (1 frame per second)
        video_path = os.path.join(plots_base, f"state_{state}_waterfall_animation.mp4")
        create_video(image_paths, video_path, fps=1)
        
        print()
    
    print("Animation creation complete!")
    print(f"Check {plots_base}/ for .gif and .mp4 files")

if __name__ == "__main__":
    main()
