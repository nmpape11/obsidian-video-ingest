import json

import pytest

from video_ingest.ocr_media import sample_frames, tiktok_slide_urls


def page(data):
    blob = json.dumps(data)
    return f'<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="x">{blob}</script>'


def slideshow(*urls):
    images = [{"imageURL": {"urlList": [u, u + "-mirror"]}} for u in urls]
    item = {"imagePost": {"images": images}}
    return page({"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": item}}}})


def test_tiktok_slide_urls_takes_first_mirror_of_each_slide():
    assert tiktok_slide_urls(slideshow("https://a/1.jpg", "https://a/2.jpg")) == [
        "https://a/1.jpg",
        "https://a/2.jpg",
    ]


@pytest.mark.parametrize(
    "html",
    [
        "<html>no data</html>",
        page({"__DEFAULT_SCOPE__": {}}),
        page({"__DEFAULT_SCOPE__": {"webapp.video-detail": {"itemInfo": {"itemStruct": {}}}}}),
        '<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{not json</script>',
    ],
)
def test_tiktok_slide_urls_returns_empty_when_not_a_slideshow(html):
    assert tiktok_slide_urls(html) == []


@pytest.fixture
def video(tmp_path):
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    path = tmp_path / "v.mp4"
    with av.open(str(path), "w") as out:
        stream = out.add_stream("mpeg4", rate=10)
        stream.width, stream.height = 64, 48
        stream.pix_fmt = "yuv420p"
        for i in range(35):  # 3.5 s at 10 fps
            img = np.full((48, 64, 3), i * 7, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(img, format="rgb24")):
                out.mux(packet)
        for packet in stream.encode():
            out.mux(packet)
    return path


def test_sample_frames_one_per_second(video):
    frames = list(sample_frames(video, fps=1.0))
    assert len(frames) == 4  # t = 0, 1, 2, 3
    assert frames[0].shape == (48, 64, 3)


def test_sample_frames_higher_rate(video):
    assert len(list(sample_frames(video, fps=2.0))) == 7  # t = 0, 0.5, ..., 3.0
