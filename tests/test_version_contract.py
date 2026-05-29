"""P0: Version contract — package version matches expected stable value."""

import memoryx


def test_package_version():
    """memoryx.__version__ must match the stable 2.0.0 release."""
    assert memoryx.__version__ == "2.0.0", (
        f"Expected 2.0.0, got {memoryx.__version__}"
    )