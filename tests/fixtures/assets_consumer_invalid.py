from __future__ import annotations

from assets import pyganini_assets_gen as assets

wrong_name = assets.path(42)
wrong_base = assets.lookup("app.css", base_path=42)
missing_asset: assets.Asset = assets.lookup("app.css")
wrong_size: str = assets.manifest()["app.css"].size
