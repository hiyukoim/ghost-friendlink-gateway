from __future__ import annotations

import datetime
import jwt
import requests

from .config import settings


def make_ghost_admin_jwt() -> str:
    key_id, secret = settings.ghost_admin_key.split(':')
    iat = int(datetime.datetime.utcnow().timestamp())
    exp = iat + 5 * 60
    header = {'alg': 'HS256', 'kid': key_id}
    payload = {'iat': iat, 'exp': exp, 'aud': '/v5/admin/'}
    token = jwt.encode(payload, bytes.fromhex(secret), algorithm='HS256', headers=header)
    return token


def ghost_api_url(slug: str) -> str:
    return (
        f"{settings.ghost_url}/ghost/api/admin/posts/slug/{slug}/"
        f"?formats=html&include=authors,tags"
    )


def get_ghost_site_settings():
    site_info = {
        'title': settings.site_title,
        'description': settings.site_description,
        'icon': settings.site_icon_url,
        'logo': settings.site_logo_url,
        'twitter': None,
        'facebook': None,
        'url': None,
        'lang': None,
    }
    try:
        settings_url = f"{settings.ghost_url}/ghost/api/content/settings/"
        if settings.ghost_content_api_key:
            settings_url += ("?key=" + settings.ghost_content_api_key)
        r = requests.get(settings_url, timeout=3)
        if r.status_code == 200:
            payload = r.json().get('settings', {})
            site_info['title'] = site_info['title'] or payload.get('title', '')
            site_info['description'] = site_info['description'] or payload.get('description', '')
            site_info['icon'] = site_info['icon'] or payload.get('icon', '')
            site_info['logo'] = site_info['logo'] or payload.get('logo', '')
            site_info['twitter'] = site_info['twitter'] or payload.get('twitter')
            site_info['facebook'] = site_info['facebook'] or payload.get('facebook')
            site_info['url'] = site_info['url'] or payload.get('url')
            site_info['lang'] = site_info['lang'] or payload.get('lang')
    except Exception:
        pass
    return site_info
