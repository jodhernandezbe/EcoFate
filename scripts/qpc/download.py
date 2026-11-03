"""Fetch the workbook over https from the allowed host, bounded in time and size."""

from __future__ import annotations

import httpx

from scripts.qpc.errors import QpcDownloadError
from scripts.qpc.release import Release

ZIP_MAGIC = b"PK\x03\x04"
OK = 200
NOT_FOUND = 404


def _check_final_url(response: httpx.Response, host: str) -> None:
    if response.url.scheme != "https" or response.url.host != host:
        raise QpcDownloadError(f"redirected away from https://{host}: {response.url}")


def _read_capped(response: httpx.Response, max_bytes: int) -> bytes:
    declared = response.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise QpcDownloadError(f"download is {declared} bytes, over the {max_bytes} byte cap")
    body = bytearray()
    for chunk in response.iter_bytes():
        body += chunk
        if len(body) > max_bytes:
            raise QpcDownloadError(f"download exceeds the {max_bytes} byte cap")
    return bytes(body)


def _status_error(response: httpx.Response, release: Release, url: str) -> QpcDownloadError:
    if response.status_code == NOT_FOUND:
        return QpcDownloadError(f"release {release.label} is not published at {url} (404)")
    return QpcDownloadError(f"HTTP {response.status_code} for release {release.label}: {url}")


def fetch_workbook(
    url: str,
    release: Release,
    *,
    client: httpx.Client,
    host: str,
    timeout: float,
    max_bytes: int,
) -> bytes:
    """Download ``url`` and return the workbook bytes.

    Raises:
        QpcDownloadError: On a network error, a non-200 answer (404 names the release), a
            redirect off ``host``, a body over ``max_bytes`` or one that is not a ZIP archive.
    """
    try:
        with client.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
            _check_final_url(response, host)
            if response.status_code != OK:
                raise _status_error(response, release, url)
            body = _read_capped(response, max_bytes)
    except httpx.HTTPError as error:
        raise QpcDownloadError(f"could not download {url}: {error}") from error
    if not body.startswith(ZIP_MAGIC):
        raise QpcDownloadError(f"{url} did not return a workbook (not a ZIP archive)")
    return body
