##############################################################################
#
# Copyright (c) 2011 Reality Jockey Ltd. and Contributors.
# This file is part of django-tornado.
#
# Django-tornado is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Django-tornado is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with django-tornado. If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

# -*- coding: utf-8 -*-

__docformat__ = "reStructuredText"

import os
import sys

from tornado.web import URLSpec
from rjdj.djangotornado.handlers import SynchronousDjangoHandler

def stdprint(self, *args, **kwargs):
    """Print in color to stdout"""
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)
    text = " ".join([str(item) for item in args])
    color = kwargs.get("color",32)
    sys.stdout.write("\033[0;%dm%s\033[0;m" % (color, text))

def get_named_urlspecs(urls):
    """ Returns Tornado-URLSpecs with names """
    
    handlers = []
    for url in urls:
        if url[1] == SynchronousDjangoHandler and \
           len(url) > 2 and \
           "django_view" in url[2]:
            name = url[2]["django_view"].__name__
        else:
            name = id(url[1])
        handlers.append(URLSpec(*url, name = name))
    return handlers

