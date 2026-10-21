"""启动入口：python run.py"""
import logging

from app import create_app
from app.config import Config

logging.basicConfig(
    level=logging.DEBUG if Config.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)

app = create_app()

if __name__ == "__main__":
    print(f"  {Config.SITE_NAME} 已启动 -> http://{Config.HOST}:{Config.PORT}")
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG, threaded=True, use_reloader=False)
