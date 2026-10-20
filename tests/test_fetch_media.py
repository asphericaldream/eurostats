import csv

from eurostats import fetch_media


class FakeResponse:
    def __init__(self, status, content=b"", content_type="image/png"):
        self.status_code = status
        self.ok = status < 400
        self.content = content
        self.headers = {"content-type": content_type}


class FakeSession:
    def __init__(self, responses):
        self.responses = responses
        self.headers = {}

    def get(self, url, timeout=None, **kwargs):
        return self.responses[url]


def test_image_file_is_stable_per_url():
    url = "https://media-cdn.example/abc.png?w=200"
    path = fetch_media.image_file("people", "007982", url)
    assert path.startswith("people/007982/") and path.endswith(".png")
    assert path == fetch_media.image_file("people", "007982", url)
    assert path != fetch_media.image_file("people", "007982", url + "&x=1")


def test_download_saves_images_and_records_status(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch_media, "MEDIA_DIR", tmp_path)
    monkeypatch.setattr(fetch_media, "PAUSE_SECONDS", 0)
    rows = [
        {"url": "https://cdn/a.png", "kind": "crest", "local_path": "crests/BAR/a.png", "status": ""},
        {"url": "https://cdn/b.png", "kind": "headshot", "local_path": "people/1/b.png", "status": ""},
        {"url": "https://cdn/c.png", "kind": "action", "local_path": "people/1/c.png", "status": ""},
    ]
    fetch_media.write_csv("images.csv", rows)
    session = FakeSession({
        "https://cdn/a.png": FakeResponse(200, b"crest"),
        "https://cdn/b.png": FakeResponse(404, content_type="text/html"),
    })
    monkeypatch.setattr(fetch_media.requests, "Session", lambda: session)

    fetch_media.download_images({"crest", "headshot"})

    assert (tmp_path / "crests/BAR/a.png").read_bytes() == b"crest"
    with open(tmp_path / "images.csv", newline="") as f:
        status = {row["url"]: row["status"] for row in csv.DictReader(f)}
    assert status == {"https://cdn/a.png": "ok", "https://cdn/b.png": "HTTP 404",
                      "https://cdn/c.png": ""}
