"""Media downloads must not export API credentials to returned CDN URLs."""
from __future__ import annotations

import httpx


def media_url(client: httpx.AsyncClient, value: str) -> httpx.URL:
    """Resolve API-relative URLs, rejecting ambiguous or credential-bearing URLs."""
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError('Invalid media URL')
    if any(ord(c) < 32 or ord(c) == 127 for c in value) or '\\' in value:
        raise ValueError('Invalid media URL')
    raw = httpx.URL(value)
    if raw.scheme and raw.scheme not in ('http', 'https'):
        raise ValueError('Media URL must use HTTP(S)')
    if raw.userinfo:
        raise ValueError('Media URL must not contain credentials')
    if value.startswith('//'):
        raw = raw.copy_with(scheme=client.base_url.scheme)
    if raw.scheme and not raw.host:
        raise ValueError('Absolute media URL requires a host')
    resolved = raw if raw.is_absolute_url else client.build_request('GET', value).url
    if not resolved.host or resolved.userinfo:
        raise ValueError('Invalid media URL')
    return resolved


def origin(url: httpx.URL) -> tuple:
    return url.scheme, url.host, url.port

def is_api_media_url(client: httpx.AsyncClient, value: str) -> bool:
    """Invalid returned URLs cannot opt into API credentials."""
    try:
        return origin(media_url(client, value)) == origin(client.base_url)
    except (ValueError, httpx.InvalidURL):
        return False


async def download_media(client: httpx.AsyncClient, url: str, *,
                         headers: dict | None = None, timeout: float | None = None,
                         authenticated: bool = True) -> httpx.Response:
    """Allow API auth only at its configured origin; never follow redirects.

    Cross-origin requests are constructed independently of the API client's
    defaults (headers, cookies, parameters and auth), then sent over its transport.
    This also preserves custom transports/proxy settings without a second pool.
    """
    target = media_url(client, url)
    options = {} if timeout is None else {'timeout': timeout}
    if authenticated and origin(target) == origin(client.base_url):
        return await client.get(target, headers=headers, follow_redirects=False, **options)
    # Only the caller's non-sensitive Accept preference is relevant to media.
    clean_headers = {'Accept': (headers or {}).get('Accept', '*/*')}
    limits = client.timeout if timeout is None else httpx.Timeout(timeout)
    request = httpx.Request('GET', target, headers=clean_headers,
                            extensions={'timeout': limits.as_dict()})
    return await client.send(request, auth=None, follow_redirects=False)
