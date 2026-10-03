from pathlib import Path


def test_content_authoring_supervisor_in_real_browser(tmp_path: Path) -> None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    try:
        from authoring_test_support import exercise_authoring

        exercise_authoring(Path(__file__).resolve().parents[1], tmp_path)
    finally:
        sys.path.pop(0)
