"""SARD Batch Runner — Runs inference directly from the kagglehub cache."""
import os
import sys
from pathlib import Path
import subprocess

# 1. Locate where kagglehub downloaded the SARD dataset
# Usually matches: ~/.cache/kagglehub/datasets/nikolasgegenava/sard-search-and-rescue/...
CACHE_DIR = Path(os.path.expanduser("~/.cache/kagglehub/datasets/nikolasgegenava/sard-search-and-rescue"))

if not CACHE_DIR.exists():
    print(f"Error: Dataset cache directory not found at {CACHE_DIR}")
    print("Please make sure you successfully ran the dataset_download command first.")
    sys.exit(1)

# 2. Find real drone images (.jpg or .png) recursively within the cache
print(f"Scanning for images in: {CACHE_DIR}")
valid_extensions = {".jpg", ".jpeg", ".png"}
image_paths = [
    p for p in CACHE_DIR.rglob("*") 
    if p.is_file() and p.suffix.lower() in valid_extensions
]

print(f"Found {len(image_paths)} images in the SARD dataset cache.")

if not image_paths:
    print("No images found inside the dataset path.")
    sys.exit(1)

# 3. Loop through the first few images to test your script on real drone frames
# (Change [:5] to a larger number or remove it to run on more files)
max_test_count = 5
print(f"\n---> Starting batch evaluation on the first {max_test_count} real frames...\n")

for i, img_path in enumerate(image_paths[:max_test_count]):
    print(f"[{i+1}/{max_test_count}] Processing: {img_path.name}")
    print("-" * 50)
    
    # We call your solid 4-bit native script using a subprocess execution
    result = subprocess.run(
        ["uv", "run", "python", "qasim_inference.py", str(img_path)],
        capture_output=False, # This lets the script print its live output/JSON directly to your screen
        text=True
    )
    print("\n" + "="*60 + "\n")

print("Batch processing complete!")