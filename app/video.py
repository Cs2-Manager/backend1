import re

_YOUTUBE_RE = re.compile(
    r"^(?:https?://)?"
    r"(?:www\.|m\.|music\.)?"
    r"(?:youtube\.com|youtu\.be)/"
    r"(?:watch\?v=|embed/|shorts/|live/)?"
    r"([\w-]{11})",
    re.IGNORECASE,
)


def extract_youtube_id(url):
    """Return the YouTube video id if `url` is a valid YouTube link, else None."""
    if not url:
        return None
    match = _YOUTUBE_RE.match(url.strip())
    if not match:
        return None
    video_id = match.group(1)
    return video_id if len(video_id) == 11 else None


def is_valid_video_url(url):
    return extract_youtube_id(url) is not None
