import warnings

from lib.terminal import use_color


def test_color_userwarning() -> None:
	use_color()  # Enable custom formatter

	warnings.warn("This should be a colored user warning", UserWarning)


def test_color_runtimewarning() -> None:
	use_color()  # Enable custom formatter

	warnings.warn("This should be a colored runtime warning", RuntimeWarning)


def test_color_deprecationwarning() -> None:
	use_color()  # Enable custom formatter

	warnings.warn("This should be a colored deprecation warning", DeprecationWarning)
