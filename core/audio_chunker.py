from pathlib import Path
import subprocess
from typing import List

MAX_CHUNK_SIZE = 18_000_000  # 18 MB (marge sécurité)


def get_audio_duration(path: Path) -> float:
    """Durée en secondes"""
    cmd = ["ffprobe", "-v", "error", "-show_entries", 
           "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def split_audio(path: Path, chunk_duration: int = 900) -> List[Path]:
    """Découpe en chunks de 15 min (900s)"""
    duration = get_audio_duration(path)
    chunks = []
    
    for i, start in enumerate(range(0, int(duration), chunk_duration)):
        chunk_path = path.parent / f"{path.stem}_chunk{i}.wav"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(path),
            "-ss", str(start), "-t", str(chunk_duration),
            "-ar", "16000", "-ac", "1", str(chunk_path)
        ], capture_output=True)
        chunks.append(chunk_path)
    
    return chunks


def merge_srt(srt_paths: List[Path], offset_seconds: List[float]) -> str:
    """Fusionne SRTs avec décalage temporel"""
    merged = []
    idx = 1
    
    for srt_path, offset in zip(srt_paths, offset_seconds):
        content = srt_path.read_text()
        for block in content.strip().split('\n\n'):
            lines = block.split('\n')
            if len(lines) >= 3:
                # Ajuster timestamps
                times = lines[1].split(' --> ')
                new_start = adjust_time(times[0], offset)
                new_end = adjust_time(times[1], offset)
                merged.append(f"{idx}\n{new_start} --> {new_end}\n{lines[2]}\n")
                idx += 1
    
    return '\n'.join(merged)


def adjust_time(timestamp: str, offset: float) -> str:
    """Ajoute offset à un timestamp SRT (format: HH:MM:SS,mmm)"""
    h, m, s_ms = timestamp.replace(',', '.').split(':')
    s, ms = s_ms.split('.')
    total = int(h)*3600 + int(m)*60 + float(s_ms) + offset
    
    h = int(total // 3600)
    m = int((total % 3600) // 60)
    s_total = total % 60
    s = int(s_total)
    ms = int((s_total - s) * 1000)
    
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

