"""
Example: How to import and use the TVQA class from other folders
"""

# Solution 1: Add parent directory to Python path (recommended for examples)
import sys
from pathlib import Path
# Add the parent directory (videomemory) to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import the TVQA class from the datasets package
from datasets import TVQA
from PIL import Image
from pathlib import Path
import shutil

def main():
    # Initialize the dataset (uses default path: datasets/tvqa)
    dataset = TVQA()
    
    # Or dataset = TVQA(dataset_path="/path/to/tvqa")
    
    # List available shows
    shows = dataset.list_shows(split="train")
    print(f"Available shows: {shows[:3]}...")
    
    # Get episodes for a show
    episodes = dataset.list_episodes("bbt", split="train")
    print(f"\nBig Bang Theory has {len(episodes)} episodes in training set")
    
    # Get a specific episode
    if episodes:
        first_ep = episodes[0]
        episode = dataset.get_episode(
            "bbt", 
            first_ep['season'], 
            first_ep['episode'], 
            split="train"
        )
        print(f"\nEpisode {episode['season']} {episode['episode']}:")
        print(f"  Questions: {episode['num_questions']}")
        print(f"  Total clips: {episode['num_clips']}")
        print(f"  Clips with questions: {episode['num_clips_with_questions']}")
        
        # Get frames for a clip
        if episode['clips']:
            clip_name = episode['clips'][0]
            frames = dataset.get_clip_frames(clip_name, show='bbt')
            print(f"\nClip {clip_name} has {len(frames)} frames")
            
            # Save first frame to outputs/ directory
            if frames:
                output_dir = Path("outputs/datasets")
                output_dir.mkdir(exist_ok=True)
                output_path = output_dir / f"{clip_name}_frame_0.jpg"
                shutil.copy2(frames[0], output_path)
                print(f"  Saved first frame to: {output_path}")

if __name__ == "__main__":
    main()

