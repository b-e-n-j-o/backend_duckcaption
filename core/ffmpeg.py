import subprocess
from pathlib import Path

def create_proxy(src: Path, out: Path):
    """
    Encode vidéo 480p proxy compressée.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-vf", "scale=854:-1",
        "-b:v", "800k",
        "-c:v", "libx264",
        "-c:a", "aac",
        str(out)
    ]
    subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out
