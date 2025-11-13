from __future__ import annotations

from ghost_gateway import create_app
from ghost_gateway.config import settings

app = create_app()


if __name__ == "__main__":
    app.run(host=settings.host, port=settings.port, debug=settings.debug)
