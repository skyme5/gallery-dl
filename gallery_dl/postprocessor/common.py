# -*- coding: utf-8 -*-

# Copyright 2018-2019 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Common classes and constants used by postprocessor modules."""

import logging


class PostProcessor():
    """Base class for postprocessors"""

    def __init__(self):
        name = self.__class__.__name__[:-2].lower()
        self.log = logging.getLogger("postprocessor." + name)

    @staticmethod
    def prepare(pathfmt):
        """Update file paths, etc."""

    @staticmethod
    def run(pathfmt):
        """Execute the postprocessor for a file"""

    @staticmethod
    def run_after(pathfmt):
        """Execute postprocessor after moving a file to its target location"""

    @staticmethod
    def finalize():
        """Cleanup"""

    def __repr__(self):
        return self.__class__.__name__
