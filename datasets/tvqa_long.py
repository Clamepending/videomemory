"""
Simple API for accessing TVQA dataset from local files.

Works with JSONL annotation files and frame directories.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict

class TVQALong:
    """API for accessing TVQA dataset from local files."""
    
    def __init__(self, dataset_path: Optional[str] = None):
        """
        Initialize the dataset.
        
        Args:
            dataset_path: Path to the TVQA dataset directory. 
                         If None, defaults to ./tvqa relative to this file.
        """
        if dataset_path is None:
            # Default to tvqa folder in the same directory as this file
            this_file = Path(__file__).parent
            self.dataset_path = this_file / "tvqa"
        else:
            self.dataset_path = Path(dataset_path)
        
        self._val_data = None
        self._train_data = None
        self._test_data = None
        self._frames_path = self.dataset_path / "videos" / "frames_hq"
    
    def _find_jsonl_file(self, filename: str) -> Optional[Path]:
        """Find a JSONL file in the dataset directory."""
        # Try current directory first
        if (self.dataset_path / filename).exists():
            return self.dataset_path / filename
        
        # Try common subdirectories
        for subdir in ['annotations', 'annotations/tvqa_qa_release', 'data', '']:
            path = self.dataset_path / subdir / filename
            if path.exists():
                return path
        
        # Search recursively
        for path in self.dataset_path.rglob(filename):
            return path
        
        return None
    
    def _load_data(self, split: str = "val") -> List[Dict]:
        """Load data for a specific split from JSONL file."""
        filename = f"tvqa_{split}.jsonl"
        jsonl_path = self._find_jsonl_file(filename)
        
        if jsonl_path is None:
            # Try alternative names
            alternatives = [
                f"{split}.jsonl",
                f"tvqa_{split}_public.jsonl",
                f"tvqa_{split}_edited.jsonl"
            ]
            for alt in alternatives:
                jsonl_path = self._find_jsonl_file(alt)
                if jsonl_path:
                    break
        
        if jsonl_path is None:
            raise FileNotFoundError(
                f"Could not find {split} JSONL file. "
                f"Looked in {self.dataset_path} and subdirectories. "
                f"Expected files like: tvqa_{split}.jsonl"
            )
        
        data = []
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data.append(json.loads(line))
        return data
    
    def _parse_vid_name(self, vid_name: str) -> Dict[str, str]:
        """
        Parse video name to extract show, season, episode info.
        
        Examples:
            "s01e01_seg01_clip_00" -> {"season": "s01", "episode": "e01", "show": "bbt"}
            "friends_s01e01_seg02_clip_14" -> {"season": "s01", "episode": "e01", "show": "friends"}
        """
        parts = vid_name.split('_')
        season = None
        episode = None
        show = None
        
        # Find season/episode pattern (s##e##)
        for part in parts:
            if part.startswith('s') and 'e' in part:
                season = part.split('e')[0]
                episode = 'e' + part.split('e')[1]
                break
        
        # Determine show from vid_name or parts
        if 'friends' in vid_name.lower():
            show = 'friends'
        elif 'bbt' in vid_name.lower() or 'big' in vid_name.lower():
            show = 'bbt'
        elif 'castle' in vid_name.lower():
            show = 'castle'
        elif 'house' in vid_name.lower():
            show = 'house'
        elif 'grey' in vid_name.lower():
            show = 'grey'
        elif 'met' in vid_name.lower() or 'himym' in vid_name.lower():
            show = 'met'
        else:
            # Try to infer from first part
            show = parts[0] if parts else 'unknown'
        
        return {
            'season': season,
            'episode': episode,
            'show': show,
            'vid_name': vid_name
        }
    
    def get_episode_questions(self, show_name: str, season: str, episode: str, 
                             split: str = "train") -> List[Dict]:
        """
        Get all questions for a specific episode.
        
        Args:
            show_name: TV show name (e.g., "The Big Bang Theory", "bbt", "friends")
            season: Season identifier (e.g., "s01", "01", "1")
            episode: Episode identifier (e.g., "e01", "01", "1")
            split: Dataset split ("train", "val", "test")
        
        Returns:
            List of question dictionaries
        """
        # Normalize inputs
        show_lower = show_name.lower()
        if 'big bang' in show_lower or show_lower == 'bbt':
            show_match = 'The Big Bang Theory'
        elif 'friends' in show_lower:
            show_match = 'Friends'
        elif 'castle' in show_lower:
            show_match = 'Castle'
        elif 'house' in show_lower:
            show_match = 'House M.D.'
        elif 'grey' in show_lower or 'anatomy' in show_lower:
            show_match = 'Grey\'s Anatomy'
        elif 'met' in show_lower or 'himym' in show_lower:
            show_match = 'How I Met You Mother'
        else:
            show_match = show_name
        
        # Normalize season/episode
        if not season.startswith('s'):
            season = f"s{season.zfill(2)}"
        if not episode.startswith('e'):
            episode = f"e{episode.zfill(2)}"
        
        episode_pattern = f"{season}{episode}"
        
        # Load data
        if split == "val":
            if self._val_data is None:
                self._val_data = self._load_data("val")
            data = self._val_data
        elif split == "train":
            if self._train_data is None:
                self._train_data = self._load_data("train")
            data = self._train_data
        elif split == "test":
            if self._test_data is None:
                self._test_data = self._load_data("test")
            data = self._test_data
        else:
            data = self._load_data(split)
        
        # Filter questions for this episode
        questions = []
        for q in data:
            if q.get('show_name') == show_match and episode_pattern in q.get('vid_name', ''):
                questions.append(q)
        
        return questions
    
    def get_clip_frames(self, vid_name: str, show: Optional[str] = None) -> List[Path]:
        """
        Get frame paths for a specific clip.
        
        Args:
            vid_name: Video clip name (e.g., "s01e01_seg01_clip_00")
            show: Show name for frame directory (e.g., "bbt", "friends"). 
                  If None, will try to infer from vid_name.
        
        Returns:
            List of frame file paths, sorted
        """
        # Determine show directory
        if show is None:
            parsed = self._parse_vid_name(vid_name)
            show = parsed['show']
        
        # Map show names to directory names
        show_dir_map = {
            'bbt': 'bbt_frames',
            'friends': 'friends_frames',
            'castle': 'castle_frames',
            'house': 'house_frames',
            'grey': 'grey_frames',
            'met': 'met_frames'
        }
        
        show_dir = show_dir_map.get(show.lower(), f"{show}_frames")
        clip_dir = self._frames_path / show_dir / vid_name
        
        if not clip_dir.exists():
            return []
        
        # Get all jpg files and sort them
        frames = sorted(clip_dir.glob("*.jpg"))
        return frames
    
    def get_episode_clips_from_frames(self, show_name: str, season: str, episode: str) -> List[str]:
        """
        Get all clip directories that exist in the frames folder for an episode.
        
        Args:
            show_name: TV show name (e.g., "The Big Bang Theory", "bbt")
            season: Season identifier (e.g., "s01", "01", "1")
            episode: Episode identifier (e.g., "e01", "01", "1")
        
        Returns:
            List of clip names that have frame directories
        """
        # Normalize inputs
        show_lower = show_name.lower()
        if 'big bang' in show_lower or show_lower == 'bbt':
            show_dir = 'bbt_frames'
        elif 'friends' in show_lower:
            show_dir = 'friends_frames'
        elif 'castle' in show_lower:
            show_dir = 'castle_frames'
        elif 'house' in show_lower:
            show_dir = 'house_frames'
        elif 'grey' in show_lower or 'anatomy' in show_lower:
            show_dir = 'grey_frames'
        elif 'met' in show_lower or 'himym' in show_lower:
            show_dir = 'met_frames'
        else:
            show_dir = f"{show_name}_frames"
        
        # Normalize season/episode
        if not season.startswith('s'):
            season = f"s{season.zfill(2)}"
        if not episode.startswith('e'):
            episode = f"e{episode.zfill(2)}"
        
        episode_pattern = f"{season}{episode}"
        frames_dir = self._frames_path / show_dir
        
        if not frames_dir.exists():
            return []
        
        # Find all clip directories matching this episode
        clips = []
        for clip_dir in frames_dir.iterdir():
            if clip_dir.is_dir() and episode_pattern in clip_dir.name:
                clips.append(clip_dir.name)
        
        clips.sort()
        return clips
    
    def get_episode(self, show_name: str, season: str, episode: str, 
                   split: str = "train", include_all_clips: bool = True) -> Dict:
        """
        Get a complete episode with questions and clip information.
        
        Args:
            show_name: TV show name (e.g., "The Big Bang Theory", "bbt")
            season: Season identifier (e.g., "s01", "01", "1")
            episode: Episode identifier (e.g., "e01", "01", "1")
            split: Dataset split ("train", "val", "test")
            include_all_clips: If True, include all clips from frames directory.
                             If False, only include clips that have questions.
        
        Returns:
            Dictionary with:
                - show: TV show name
                - season: Season identifier
                - episode: Episode identifier
                - questions: All questions for this episode
                - clips: List of clip names (all available or only with questions)
                - clips_with_questions: List of clips that have questions
                - num_questions: Number of questions
                - num_clips: Total number of clips
                - num_clips_with_questions: Number of clips that have questions
                - total_frames: Total number of frames across all clips in the episode
        """
        questions = self.get_episode_questions(show_name, season, episode, split)
        
        # Extract unique clips from questions
        clips_with_questions = list(set(q.get('vid_name', '') for q in questions if q.get('vid_name')))
        clips_with_questions.sort()
        
        if include_all_clips:
            # Get all clips from frames directory
            all_clips = self.get_episode_clips_from_frames(show_name, season, episode)
            clips = all_clips
        else:
            clips = clips_with_questions
        
        # Calculate total frames across all clips
        total_frames = 0
        for clip_name in clips:
            clip_frames = self.get_clip_frames(clip_name, show=show_name)
            total_frames += len(clip_frames)
        
        return {
            'show': show_name,
            'season': season,
            'episode': episode,
            'questions': questions,
            'clips': clips,
            'clips_with_questions': clips_with_questions,
            'num_questions': len(questions),
            'num_clips': len(clips),
            'num_clips_with_questions': len(clips_with_questions),
            'total_frames': total_frames
        }
    
    def list_shows(self, split: str = "train") -> List[str]:
        """List all TV shows in the dataset."""
        if split == "val":
            if self._val_data is None:
                self._val_data = self._load_data("val")
            data = self._val_data
        elif split == "train":
            if self._train_data is None:
                self._train_data = self._load_data("train")
            data = self._train_data
        elif split == "test":
            if self._test_data is None:
                self._test_data = self._load_data("test")
            data = self._test_data
        else:
            data = self._load_data(split)
        
        shows = list(set(q.get('show_name', '') for q in data if q.get('show_name')))
        return sorted(shows)
    
    def list_episodes(self, show_name: str, split: str = "train") -> List[Dict]:
        """
        List episodes for a show.
        
        Returns:
            List of dicts with 'season', 'episode', 'num_questions' keys
        """
        if split == "val":
            if self._val_data is None:
                self._val_data = self._load_data("val")
            data = self._val_data
        elif split == "train":
            if self._train_data is None:
                self._train_data = self._load_data("train")
            data = self._train_data
        elif split == "test":
            if self._test_data is None:
                self._test_data = self._load_data("test")
            data = self._test_data
        else:
            data = self._load_data(split)
        
        # Normalize show name
        show_lower = show_name.lower()
        if 'big bang' in show_lower or show_lower == 'bbt':
            show_match = 'The Big Bang Theory'
        elif 'friends' in show_lower:
            show_match = 'Friends'
        elif 'castle' in show_lower:
            show_match = 'Castle'
        elif 'house' in show_lower:
            show_match = 'House M.D.'
        elif 'grey' in show_lower or 'anatomy' in show_lower:
            show_match = 'Grey\'s Anatomy'
        elif 'met' in show_lower or 'himym' in show_lower:
            show_match = 'How I Met You Mother'
        else:
            show_match = show_name
        
        # Group by episode
        episode_questions = defaultdict(list)
        for q in data:
            if q.get('show_name') == show_match:
                vid_name = q.get('vid_name', '')
                # Extract season/episode from vid_name
                for part in vid_name.split('_'):
                    if part.startswith('s') and 'e' in part:
                        episode_key = part  # e.g., "s01e01"
                        episode_questions[episode_key].append(q)
                        break
        
        episodes = []
        for ep_key, questions in episode_questions.items():
            season = ep_key.split('e')[0]
            episode = 'e' + ep_key.split('e')[1]
            episodes.append({
                'season': season,
                'episode': episode,
                'num_questions': len(questions)
            })
        
        # Sort by season, then episode
        episodes.sort(key=lambda x: (x['season'], x['episode']))
        return episodes


# Example usage
if __name__ == "__main__":
    dataset = TVQALong(dataset_path="./tvqa")
    
    print("=" * 70)
    print("TVQA Dataset Example")
    print("=" * 70)
    
    try:
        # List shows
        shows = dataset.list_shows(split="train")
        print(f"\nAvailable shows: {shows[:5]}...")
        
        # Get first episode of Big Bang Theory
        episodes = dataset.list_episodes("bbt", split="train")
        if episodes:
            first_ep = episodes[0]
            print(f"\nFirst BBT episode: {first_ep['season']} {first_ep['episode']} ({first_ep['num_questions']} questions)")
            
            episode_data = dataset.get_episode("bbt", first_ep['season'], first_ep['episode'], split="train")
            print(f"\nEpisode: {episode_data['show']} {episode_data['season']} {episode_data['episode']}")
            print(f"Questions: {episode_data['num_questions']}")
            print(f"Clips: {episode_data['num_clips']}")
            
            if episode_data['questions']:
                print(f"\nSample questions:")
                for q in episode_data['questions'][:3]:
                    print(f"  Q: {q.get('q', '')[:60]}...")
                    print(f"    Clip: {q.get('vid_name', '')}")
                    print(f"    Time: {q.get('ts', '')}")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
