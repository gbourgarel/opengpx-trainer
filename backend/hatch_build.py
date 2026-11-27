"""Hatch build hook: ship the built frontend inside the wheel, as ``opengpx_trainer/web``.

A friend then installs one file (``uv tool install opengpx_trainer-….whl``) without Node. Run
``npm run build`` in ``frontend/`` first, then ``uv build --wheel`` here (not a plain
``uv build``: the wheel would be built from the sdist, which has no ``frontend/``). Editable
installs (``uv sync``) skip the hook and the app serves ``frontend/dist`` from the repository.
"""

from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class FrontendBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        dist = Path(self.root).parent / "frontend" / "dist"
        if not (dist / "index.html").is_file():
            raise RuntimeError(f"{dist} not found: run `npm run build` in frontend/ first")
        build_data["force_include"][str(dist)] = "opengpx_trainer/web"
        # MIT: the notice goes with every copy (the file is at the repository root)
        build_data["force_include"][str(Path(self.root).parent / "LICENSE")] = (
            "opengpx_trainer/LICENSE"
        )
