"""ANSI-coloured warning formatting utilities.

This module provides simple ANSI colour constants and helpers to install a
custom warning formatter into the :mod:`warnings` module so Python warnings
are printed with a colour corresponding to their category.

Example:
	>>> from src.lib import terminal
	>>> terminal.use_color()
	# subsequent warnings will be coloured
"""

import warnings
from collections.abc import Callable

# ANSI terminal colours
RED = "\033[31m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
CYAN = "\033[36m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
RESET = "\033[0m"

__all__ = [
	"BLUE",
	"CYAN",
	"GREEN",
	"MAGENTA",
	"RED",
	"RESET",
	"YELLOW",
	"colored_formatwarning",
	"use_color",
]


def _color_for(category: type[Warning]) -> str:
	"""Return an ANSI colour code for the given warning category.

	Args:
		category: A warning class (a subclass of :class:`Warning`).

	Returns:
		A string containing an ANSI escape sequence representing the colour
		for the provided warning category.
	"""
	try:
		if issubclass(category, UserWarning):
			return YELLOW
		if issubclass(category, RuntimeWarning):
			return RED
		if issubclass(category, DeprecationWarning):
			return MAGENTA
	except TypeError:
		# If `category` is not a class, fall back to default colour.
		return CYAN
	return CYAN


# Keep the original formatter so we can delegate to it.
original_formatwarning: Callable[..., str] = warnings.formatwarning


def colored_formatwarning(
	message: object,
	category: type[Warning],
	filename: str,
	lineno: int,
	line: str | None = None,
) -> str:
	"""Format a warning message with an ANSI colour prefix and reset suffix.

	This function is compatible with the signature expected by
	:func:`warnings.formatwarning` and can be installed as the global
	formatter for the :mod:`warnings` module.

	Args:
		message: The warning message (may be a string or warning instance).
		category: The warning class.
		filename: The name of the file where the warning was issued.
		lineno: The line number in the file.
		line: The source line text, if available.

	Returns:
		The coloured formatted warning string.
	"""
	color = _color_for(category)
	formatted = original_formatwarning(message, category, filename, lineno, line)
	return color + formatted + RESET


def use_color() -> None:
	"""Install the coloured warning formatter into :mod:`warnings`.

	After calling this function, calls to :func:`warnings.warn` will use the
	coloured formatter defined in :func:`colored_formatwarning`.
	"""
	warnings.formatwarning = colored_formatwarning
