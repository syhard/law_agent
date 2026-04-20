from app.api import app
from app.config import get_settings


if __name__ == "__main__":
    settings = get_settings()
    app.run(host=settings.host, port=settings.port, debug=settings.debug)
