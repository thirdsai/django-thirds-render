"""A small thirds.ai API client. Standard library only.

The API key is sent in the Authorization header and nowhere else. It is never part of
an exception message, a repr or a log line. Signed download links are used once and
not kept on the result.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field


USER_AGENT = "django-thirds-render/0.1.0"
_JOB_ID = re.compile(r"^(pdf|image)_[0-9a-f]{32}$")


class ThirdsError(Exception):
    """The API refused a request, a render failed, or the file could not be fetched."""

    def __init__(self, message, status=None, code=None, job_id=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.job_id = job_id


@dataclass
class RenderResult:
    content: bytes
    media_type: str
    job_id: str
    job: dict = field(repr=False)

    @property
    def extension(self):
        return {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(
            self.media_type, "bin"
        )


class ThirdsClient:
    """Starts a render, waits for it and downloads the file.

    ``ThirdsClient()`` reads the key and options from Django settings. Pass ``api_key``
    and ``base_url`` to use it outside Django.
    """

    def __init__(self, api_key=None, base_url=None, timeout=None, deadline=None, poll_interval=None):
        if api_key is None or base_url is None or timeout is None or deadline is None or poll_interval is None:
            from . import conf

            api_key = conf.api_key() if api_key is None else api_key
            base_url = conf.option("BASE_URL") if base_url is None else base_url
            timeout = conf.option("TIMEOUT") if timeout is None else timeout
            deadline = conf.option("DEADLINE") if deadline is None else deadline
            poll_interval = conf.option("POLL_INTERVAL") if poll_interval is None else poll_interval
        self._key = (api_key or "").strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.deadline = deadline
        self.poll_interval = poll_interval

    def __repr__(self):
        return f"ThirdsClient(base_url={self.base_url!r}, key={'set' if self._key else 'missing'})"

    @property
    def has_key(self):
        return bool(self._key)

    # Public API

    def render(self, kind, body, idempotency_key=None):
        """POST /v1/pdf or /v1/image, wait for the job, return a RenderResult."""
        if kind not in ("pdf", "image"):
            raise ValueError("kind must be 'pdf' or 'image'")
        if not self._key:
            raise ThirdsError("THIRDS_API_KEY is not set. No request was sent.", code="missing_key")
        key = idempotency_key or f"django-{uuid.uuid4()}"
        job = self._call("POST", f"/v1/{kind}", body, idempotency_key=key)
        stop = time.monotonic() + self.deadline
        while job.get("status") in ("queued", "running"):
            if time.monotonic() > stop:
                raise ThirdsError("The render did not finish in time.", code="timeout", job_id=job.get("id"))
            time.sleep(self.poll_interval)
            job = self._call("GET", f"/v1/{kind}/{urllib.parse.quote(job['id'])}")
        if job.get("status") != "succeeded":
            err = job.get("error") or {}
            raise ThirdsError(
                f"The render {job.get('status')}: {err.get('code', 'unknown')}",
                code=err.get("code") or job.get("status"),
                job_id=job.get("id"),
            )
        download = (job.get("download") or {}).get("url")
        if not download:
            raise ThirdsError("The job has no download link.", code="no_download", job_id=job.get("id"))
        content, media_type = self._download(urllib.parse.urljoin(self.base_url + "/", download))
        public = {k: v for k, v in job.items() if k != "download"}
        return RenderResult(content=content, media_type=media_type, job_id=job["id"], job=public)

    def pdf(self, html=None, *, template_id=None, data=None, version=None, idempotency_key=None, **options):
        return self.render("pdf", build_body(html, template_id, data, version, options), idempotency_key)

    def image(self, html=None, *, template_id=None, data=None, version=None, idempotency_key=None,
              format="png", width=None, height=None, **options):
        image = {"format": format, **({"width": int(width)} if width else {}), **({"height": int(height)} if height else {})}
        image.update(options.pop("image", {}))
        options["image"] = image
        return self.render("image", build_body(html, template_id, data, version, options), idempotency_key)

    # HTTP

    def _call(self, method, path, body=None, idempotency_key=None):
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json", "User-Agent": USER_AGENT}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
            headers["Idempotency-Key"] = idempotency_key
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                return json.load(res)
        except urllib.error.HTTPError as e:
            try:
                err = json.loads(e.read() or b"{}").get("error") or {}
            except ValueError:
                err = {}
            code = err.get("code") or f"http_{e.code}"
            raise ThirdsError(f"thirds.ai answered {e.code} {code}: {err.get('message', '')}".strip(),
                              status=e.code, code=code) from None
        except urllib.error.URLError as e:
            raise ThirdsError(f"Could not reach thirds.ai: {e.reason}", code="network") from None

    def _download(self, url):
        # The signed link needs no key, so none is sent. The link is not stored or logged.
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as res:
                return res.read(), res.headers.get_content_type()
        except urllib.error.URLError:
            raise ThirdsError("The rendered file could not be downloaded.", code="download_failed") from None


def build_body(html, template_id, data, version, options):
    """The request body for one of the three input modes: raw HTML, inline template, saved template."""
    if (html is None) == (template_id is None):
        raise ValueError("Pass exactly one of html or template_id.")
    body = {k: v for k, v in options.items() if v is not None}
    if template_id is not None:
        body["template_id"] = template_id
        body["data"] = data or {}
        if version:
            body["version"] = int(version)
    else:
        body["html"] = html
        if data is not None:
            body["data"] = data
    return body
