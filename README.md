# Ghost FriendLink Gateway

A lightweight Flask-based gateway for sharing private or paid Ghost posts via unique access tokens.

Each token is unique, can be generated per platform (Fanbox, Ko-fi, Patreon, etc.), and can be revoked anytime.
Designed to run seamlessly on **Coolify** or any Docker-based host.
※ This repo is vibe coded with Chat GPT-5.

## Features

- 🔗 Generate unique access links per post or platform  
- 🧱 Fully environment-variable driven (no hardcoded URLs)  
- 🪶 Invalid links redirect to your Ghost signup or paywall page  
- 🧹 Simple SQLite-based token storage  
- ⚡ Compatible with Ghost v5+ and Python 3.11+

## Environment Variables

| Variable | Description | Example |
|-----------|--------------|----------|
| `GHOST_URL` | Your Ghost blog base URL | `https://yourblog.com` |
| `GHOST_ADMIN_KEY` | Admin API key from Ghost Integrations | `abc123:verylongsecret` |
| `APP_BASE_URL` | Public base URL of this app | `https://gateway.yourdomain.com` |
| `DEFAULT_REDIRECT` | (Optional) Fallback URL for invalid tokens | `https://yourblog.com/#/portal/signup` |
| `PORT` | Internal server port | `5000` |

## Example Usage

### Generate a token

```
GET /generate/my-paid-post?ref=fanbox
```

Response:

```json
{
  "slug": "my-paid-post",
  "ref": "james",
  "token_url": "https://gateway.yourdomain.com/read/07ec6b8f-..."
}
```

### Revoke a token

```
POST /revoke/<token>
```

### Access content

```
GET /read/<token>
```

If valid → returns the Ghost post HTML  
If invalid → redirects to your configured signup/paywall page

## Deploying on Coolify

1. Create a new **Dockerfile App** in Coolify  
2. Point it to this repository  
3. Set environment variables under “Configuration”  
4. (Optional) Map a persistent volume to `/app/data` for token storage  
5. Deploy 🚀

---

MIT License  
© 2025 Yuko
