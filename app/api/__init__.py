"""蓝图注册"""
from .auth import bp as auth_bp
from .catalog import bp as catalog_bp
from .download import bp as download_bp
from .playlists import bp as playlist_bp
from .jobs import bp as jobs_bp
from .admin import bp as admin_bp


def register_blueprints(app):
    for bp in (auth_bp, catalog_bp, download_bp, playlist_bp, jobs_bp, admin_bp):
        app.register_blueprint(bp)
