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

from threading import Thread, Lock

from cStringIO import StringIO

from tornado.web import RequestHandler, asynchronous
from tornado.ioloop import IOLoop
from tornado.wsgi import WSGIContainer

from django.conf import settings
from django.core.handlers.base import BaseHandler
from django.core.handlers.wsgi import WSGIRequest
from django.core import signals
from django.http import (HttpRequest,
                         QueryDict,
                         HttpResponse,
)

try:
    from django.http.multipartparser import MultiPartParser
    from django.utils.datastructures import MultiValueDict
except ImportError:
    from django.http import MultiPartParser, MultiValueDict


class DjangoRequest(WSGIRequest):
    """Tornado Request --> Django Request"""

    _tornado_request = None
    _cookies = None

    def __init__(self, tornado_request_type, cookies=None):
        self._tornado_request = tornado_request_type
        self._cookies = cookies
        environ = WSGIContainer.environ(tornado_request_type)
        super(DjangoRequest,self).__init__(environ)
        self.tornado_to_django()

    def tornado_to_django(self):
        tr = self._tornado_request
        
        if not tr.method:
            raise KeyError("Missing method in request")
        if tr.method not in ["GET","POST"]:
            raise ValueError("Method must be GET or POST")

        if not self._cookies:
            import Cookie
            self._cookies = Cookie.BaseCookie()
            cookies = tr.headers.get("Cookie","")
            if cookies:
                self._cookies.load(str(cookies))
        for k,v in self._cookies.items():
            self.COOKIES[k] = v.value

    def build_absolute_uri(self,location=None):
        uri = super(DjangoRequest,self).build_absolute_uri(location)
        return unicode(uri)

    def __setitem__(self, key, value):
        if hasattr(self,key):
            setattr(self,key,value)
        else:
            self.META[key] = value

    def _load_file_upload_handlers(self):
        handlers = []
        for handler in settings.FILE_UPLOAD_HANDLERS:
            tmp = handler.split(".")
            cls = tmp.pop()
            module = ".".join(tmp)
            imp = __import__(module, fromlist = [cls])
            handlers.append(getattr(imp, cls)())
            
        return handlers

    @property
    def raw_get_data(self):
        return self._tornado_request.query

    @property
    def raw_post_data(self):
        return self._tornado_request.body



class CallableType:

    def __init__(self, func):
        self.func = func

    def __call__(self, *args, **kwargs):
        return self.func(*args, **kwargs)



class MiddlewareProvider(BaseHandler):
    """Lazy loading Middleware"""

    initLock = Lock()

    def __call__(self):
        if self._request_middleware is None:
            self.initLock.acquire()
            try:
                try:
                    # Check that middleware is still uninitialised.
                    if self._request_middleware is None:
                        self.load_middleware()
                except:
                    # Unload whatever middleware we got
                    self._request_middleware = None
                    raise
            finally:
                self.initLock.release()


middleware_provider = MiddlewareProvider()


class SynchronousDjangoHandler(RequestHandler):
    """Synchronous Handler for Django views"""

    _view = None
    _handler_name = ""

    def _get_stacktrace(self):
        import traceback
        self.set_status(500)
        tb = traceback.format_exc(limit=10)
        print tb
        self.set_header("Content-Type", "text/plain; encoding=utf-8")
        return tb

    def initialize(self, django_view, **kwargs):
        self._view = CallableType(django_view)
        self._handler_name = kwargs.get("handler_name","synchronous_django_handler")

    def prepare(self):
        pass
            
    def convert_response(self, response):
        self.set_status(response.status_code)
        for k,v in response.items():
            self.set_header(k.encode("utf-8"), v.encode("utf-8"))
        if hasattr(response, "render"):
            response.render()
        self.write(response.content.encode("utf-8"))

    def return_response(self, response):
        """Response can either be a HttpResponse object or string"""
        if self.request.connection.stream.closed():
            signals.request_finished.send(sender=middleware_provider.__class__)
            return
        if isinstance(response, HttpResponse):
            self.convert_response(response)
        else:
            self.write(str(response).encode("utf-8"))
        signals.request_finished.send(sender=middleware_provider.__class__)
        self.finish()

    def _apply_request_middleware(self, request):
        signals.request_started.send(sender=middleware_provider.__class__)
        middleware_provider()
        
        for func in middleware_provider._request_middleware:
            func(request)
            
        return request

    def _apply_response_middleware(self, response):
        middleware_provider()
        for func in middleware_provider._response_middleware:
            func(response)
        return response
    
    def process_request(self, *args, **kwargs): 
        """ Actual view execution """
        
        response = None
        req = DjangoRequest(self.request, self.cookies)
        req = self._apply_request_middleware(req)
        
        if settings.DEBUG:
            try:
                response = self._view(req, *args, **kwargs)
            except Exception, e:
                response = self._get_stacktrace()
        else:
            response = self._view(req, *args, **kwargs)

        self.return_response(response)


    get = post = put = delete = head = options = process_request

class DjangoHandler(SynchronousDjangoHandler):
    """Asynchronous Handler for Django views"""

    def start_thread(self, request, cookies, *args, **kwargs):
        request = DjangoRequest(request, cookies)
        request = self._apply_request_middleware(request)
        thread = Thread(target = self.worker,
                        args = (request,) + args,
                        kwargs = kwargs)
        thread.daemon = True
        thread.start()

    def worker(self, *args, **kwargs):
        """Worker that is processes in separate thread"""
        if settings.DEBUG:
            try:
                res = self._view(*args, **kwargs)
            except Exception, e:
                res = self._get_stacktrace()
        else:
            res = self._view(*args, **kwargs)

        cb = self.async_callback(self.return_response, res)
        io_loop = IOLoop.instance()
        io_loop.add_callback(cb)

    def prepare(self):
        """Override prepare"""
        # this would be the place for Django Middleware

    @asynchronous
    def get(self, *args, **kwargs):
        """GET Handler"""
        self.start_thread(self.request, self.cookies, *args, **kwargs)

    @asynchronous
    def post(self, *args, **kwargs):
        """POST Handler"""
        self.start_thread(self.request, self.cookies, *args, **kwargs)
