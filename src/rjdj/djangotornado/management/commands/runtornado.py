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

import logging
from optparse import make_option
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from tornado.web import RequestHandler
from tornado.options import parse_command_line
from rjdj.djangotornado.signals import tornado_exit
from rjdj.djangotornado.utils import get_named_urlspecs
from rjdj.djangotornado.shortcuts import set_application


logger = logging.getLogger()

class WelcomeHandler(RequestHandler):

    def get(self):
        import django
        self.set_header("Content-Type", "text/plain;charset=utf-8")
        self.write("Tornado Web Server with Django %s" % django.get_version())
        self.finish()


class Command(BaseCommand):
    option_list = BaseCommand.option_list
    help = "Starts a single threaded Tornado web server."
    args = '[optional port number, or ipaddr:port]'

    can_import_settings = True

    def handle(self, addrport='', *args, **options):
        """Handle command call"""

        if args:
            raise CommandError('Usage is runserver %s' % self.args)
        if not addrport:
            self.addr = ''
            self.port = '8000'
        else:
            try:
                self.addr, self.port = addrport.split(':')
            except ValueError:
                self.addr, self.port = '', addrport
        if not self.addr:
            self.addr = '127.0.0.1'

        if not self.port.isdigit():
            raise CommandError("%r is not a valid port number." % port)

        self.quit_command = (sys.platform == 'win32') and 'CTRL-BREAK' or 'CONTROL-C'
        self.inner_run()

    def admin_media(self):
        """Return path and url of development admin media"""
        import django.contrib.admin as admin_media
        path = os.path.join(admin_media.__path__[0],'media')
        url = hasattr(settings,"ADMIN_MEDIA_PREFIX") and \
              settings.ADMIN_MEDIA_PREFIX or "/admin-media/"
        return (path, url,)

    def get_handler(self, *args, **kwargs):
        """Return Tornado application with Django WSGI handlers"""
        from django.core.handlers.wsgi import WSGIHandler
        from tornado import wsgi
        from tornado.web import FallbackHandler, StaticFileHandler

        # Patch prepare method from Tornado's FallbackHandler
        from rjdj.djangotornado import patches
        FallbackHandler.prepare = patches.patch_prepare(FallbackHandler.prepare)

        django_app = wsgi.WSGIContainer(WSGIHandler())
        handlers = []
        try:
            urls =  __import__(settings.ROOT_URLCONF,
                               fromlist=[settings.ROOT_URLCONF])

            if hasattr(urls,"tornado_urls"):
                handlers = get_named_urlspecs(urls.tornado_urls)

        except ImportError:
            logger.warn("No Tornado URL specified.")

        admin_media_path, admin_media_url = self.admin_media()
        handlers += (
            (r'/_', WelcomeHandler),
            (r'%s(.*)' % admin_media_url, StaticFileHandler, {"path": admin_media_path}),
            (r'.*', FallbackHandler, dict(fallback=django_app)),
            )
        return patches.DjangoApplication(handlers, **{"debug": settings.DEBUG})

    def run(self, *args, **options):
        """Run application either with or without autoreload"""
        self.inner_run()

    def inner_run(self):
        """Get handler and start IOLoop"""
        import django
        from tornado import httpserver, ioloop

        parse_command_line()

        print "Validating models..."
        self.validate(display_num_errors=True)
        logger.info("\nDjango version %(version)s, using settings %(settings)r\n"
                   "Server is running at http://%(addr)s:%(port)s/\n"
                   "Quit the server with %(quit_command)s.\n" % {
                       "version": self.get_version(),
                       "settings": settings.SETTINGS_MODULE,
                       "addr": self.addr,
                       "port": self.port,
                       "quit_command": self.quit_command,
                   })

        app = self.get_handler()
        set_application(app)

        server = httpserver.HTTPServer(app)
        server.listen(int(self.port), address=self.addr)
        try:
            ioloop.IOLoop.instance().start()
        except KeyboardInterrupt:
            logger.warn("Shutting down Tornado ...")
        finally:
            tornado_exit.send_robust(sender=self)
            sys.exit(0)
