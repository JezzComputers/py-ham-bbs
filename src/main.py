"""
Demonstrates the warnings colouring system.
Replace with BBS
"""

from warnings import warn

from lib.terminal import use_color

warn("This is a userwarning", UserWarning)
warn("This is a runtimewarning", RuntimeWarning)
warn("This is a deprecationwarning", DeprecationWarning)
use_color()
warn("This is a userwarning", UserWarning)
warn("This is a runtimewarning", RuntimeWarning)
warn("This is a deprecationwarning", DeprecationWarning)
