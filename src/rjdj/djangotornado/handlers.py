##############################################################################
#
# Copyright (c) 2011 Reality Jockey Ltd. and Contributors.
# All Rights Reserved.
#
##############################################################################

# -*- coding: utf-8 -*-

__docformat__ = "reStructuredText"

from threading import Thread, Lock

from tornado.web import RequestHandler, asynchronous
from tornado.ioloop import IOLoop

from django.http import (HttpRequest,
                         QueryDict , MultiValueDict,
                         HttpResponse,
                         )
from django.conf import settings
from django.core.handlers.base import BaseHandler

class DjangoRequest(HttpRequest):
    """Tornado Request --> Django Request"""

    _tornado_request = None
    _cookies = None

    def __init__(self, tornado_request_type, cookies=None):
        self._tornado_request = tornado_request_type
        self._cookies = cookies
        super(DjangoRequest,self).__init__()
        self.tornado_to_django()

    def tornado_to_django(self):
        tr = self._tornado_request

        if not tr.method:
            raise KeyError("Missing method in request")
        if tr.method not in ["GET","POST"]:
            raise ValueError("Method must be GET or POST")

        self.method = tr.method
        self.path = tr.uri
        self.path_info = ''

        self.GET = QueryDict(self.raw_get_data, encoding=self._encoding)
        self.POST = QueryDict(self.raw_post_data, encoding=self._encoding)
        self.FILES = MultiValueDict({})

        self.META["SERVER_NAME"] = tr.host
        self.META["HTTP_HOST"] = tr.host
        self.META["PROTOCOL"] = tr.protocol
        self.META["REMOTE_ADDR"] = tr.remote_ip

        self.COOKIES = {}
        if not self._cookies:
            import Cookie
            self._cookies = Cookie.BaseCookie()
            cookies = tr.headers.get("Cookie","")
            if cookies:
                self._cookies.load(str(cookies))
        for k,v in self._cookies.items():
            self.COOKIES[k] = v.value

        # Authentication Middleware not implemented yet
        self.user = None
        self.session = {}

    def build_absolute_uri(self,location=None):
        uri = super(DjangoRequest,self).build_absolute_uri(location)
        return unicode(uri)

    def __setitem__(self, key, value):
        if hasattr(self,key):
            setattr(self,key,value)
        else:
            self.META[key] = value

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

    def process_request(self, request):
        return request

    def process_response(self, response):
        return response


middleware_provider = MiddlewareProvider()


class SynchronousDjangoHandler(RequestHandler):
    """Synchronous Handler for Django views"""

    _view = None

    def _get_stacktrace(self):
        import traceback
        self.set_status(500)
        tb = traceback.format_exc(limit=10)
        self.set_header("Content-Type", "text/plain; encoding=utf-8")
        return tb

    def initialize(self, django_view):
        self._view = CallableType(django_view)

    def prepare(self):
        response = None
        req = DjangoRequest(self.request, self.cookies)
        req = self._apply_request_middleware(req)
        if settings.DEBUG:
            try:
                response = self._view(req)
            except Exception, e:
                response = self._get_stacktrace()
        else:
            response = self._view(req)

        self.return_response(response)

    def convert_response(self, response):
        self.set_status(response.status_code)
        for k,v in response.items():
            self.set_header(k.encode("utf-8"), v.encode("utf-8"))
        if hasattr(response, "render"):
            response.render()
        self.write(response.content.encode("utf-8"))

    def return_response(self, response):
        """Response can either be a HttpResponse object or string"""
        if isinstance(response, HttpResponse):
            self.convert_response(response)
        else:
            self.write(str(response).encode("utf-8"))
        self.finish()

    def _apply_request_middleware(self, request):
        middleware_provider()
        for func in middleware_provider._request_middleware:
            func(request)
        return request


    def _apply_response_middleware(self, response):
        middleware_provider()
        for func in middleware_provider._response_middleware:
            func(response)
        return response


class DjangoHandler(SynchronousDjangoHandler):
    """Asynchronous Handler for Django views"""

    def start_thread(self, request, cookies, *args):
        request = DjangoRequest(request, cookies)
        request = self._apply_request_middleware(request)
        thread = Thread(target = self.worker,
                        args = (request,) + args,
                        kwargs = {})
        thread.daemon = True
        thread.start()

    def worker(self, *args):
        """Worker that is processes in separate thread"""
        if settings.DEBUG:
            try:
                res = self._view(*args)
            except Exception, e:
                res = self._get_stacktrace()
        else:
            res = self._view(*args)

        cb = self.async_callback(self.return_response, res)
        io_loop = IOLoop.instance()
        io_loop.add_callback(cb)

    def prepare(self):
        """Override prepare"""
        # this would be the place for Django Middleware

    @asynchronous
    def get(self, *args):
        """GET Handler"""
        self.start_thread(self.request, self.cookies, *args)

    @asynchronous
    def post(self, *args):
        """POST Handler"""
        self.start_thread(self.request, self.cookies, *args)
