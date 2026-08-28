from __future__ import annotations

from assets import pyganini_assets_gen as assets

asset: assets.Asset = assets.manifest()["app.css"]
asset_path: str = assets.path("app.css")
optional_path: str | None = assets.lookup("missing")
asset_size: int = asset.size
