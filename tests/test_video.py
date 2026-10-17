def test_video_extract_valid_ids():
    from app.video import extract_youtube_id

    assert (
        extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )
    assert extract_youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert (
        extract_youtube_id("https://www.youtube.com/embed/dQw4w9WgXcQ")
        == "dQw4w9WgXcQ"
    )


def test_video_rejects_invalid_urls():
    from app.video import extract_youtube_id, is_valid_video_url

    assert extract_youtube_id("") is None
    assert extract_youtube_id(None) is None
    assert extract_youtube_id("https://example.com/video") is None
    assert is_valid_video_url("not-a-url") is False
