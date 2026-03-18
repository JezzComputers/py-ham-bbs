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

# Standard 8 colors
BLACK = "\033[30m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

# Bright (high-intensity) colors
BRIGHT_BLACK = "\033[90m"
BRIGHT_RED = "\033[91m"
BRIGHT_GREEN = "\033[92m"
BRIGHT_YELLOW = "\033[93m"
BRIGHT_BLUE = "\033[94m"
BRIGHT_MAGENTA = "\033[95m"
BRIGHT_CYAN = "\033[96m"
BRIGHT_WHITE = "\033[97m"

# Reset
RESET = "\033[0m"


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
			return BRIGHT_YELLOW
		if issubclass(category, DeprecationWarning):
			return BRIGHT_MAGENTA
		if issubclass(category, RuntimeWarning):
			return BRIGHT_RED
		if issubclass(category, SyntaxWarning):
			return BRIGHT_BLUE
		if issubclass(category, FutureWarning):
			return BRIGHT_GREEN
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

if __name__ == "__main__":
	print(
		f"{BLACK}██{RESET} BLACK\n"
		f"{RED}██{RESET} RED\n"
		f"{GREEN}██{RESET} GREEN\n"
		f"{YELLOW}██{RESET} YELLOW\n"
		f"{BLUE}██{RESET} BLUE\n"
		f"{MAGENTA}██{RESET} MAGENTA\n"
		f"{CYAN}██{RESET} CYAN\n"
		f"{WHITE}██{RESET} WHITE\n"
		f"{BRIGHT_BLACK}██{RESET} BRIGHT_BLACK\n"
		f"{BRIGHT_RED}██{RESET} BRIGHT_RED\n"
		f"{BRIGHT_GREEN}██{RESET} BRIGHT_GREEN\n"
		f"{BRIGHT_YELLOW}██{RESET} BRIGHT_YELLOW\n"
		f"{BRIGHT_BLUE}██{RESET} BRIGHT_BLUE\n"
		f"{BRIGHT_MAGENTA}██{RESET} BRIGHT_MAGENTA\n"
		f"{BRIGHT_CYAN}██{RESET} BRIGHT_CYAN\n"
		f"{BRIGHT_WHITE}██{RESET} BRIGHT_WHITE"
	)
