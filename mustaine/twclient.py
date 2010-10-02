from urlparse import urlparse
import base64

from OpenSSL import SSL
from twisted.internet import ssl, reactor
from twisted.internet.protocol import ClientFactory, Protocol
from twisted.web.client import getPage
from twisted.internet.defer import Deferred

from mustaine.encoder import encode_object
from mustaine.parser import Parser
from mustaine.protocol import Call, Fault
from mustaine import __version__

class CtxFactory( ssl.ClientContextFactory ):

    def __init__( self, key_file = None, cert_file = None ):
        self._keyf = key_file
        self._certf = cert_file

    def getContext(self):
        self.method = SSL.SSLv23_METHOD
        ctx = ssl.ClientContextFactory.getContext( self )
        ctx.use_certificate_file( self._certf )
        ctx.use_privatekey_file( self._keyf )

        return ctx

class ProtocolError(Exception):
    """ Raised when an HTTP error occurs """
    def __init__(self, url, status, reason):
        self._url    = url
        self._status = status
        self._reason = reason

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return "<ProtocolError for {0}: {1} {2}>".format(self._url,
                                                         self._status,
                                                         self._reason)


class AsyncHessianProxy(object):

    def __init__( self, service_uri,
                  credentials   = None,
                  key_file      = None,
                  cert_file     = None,
                  timeout       = 10,
                  error_factory = None ):

        # Prepare the headers
        self._headers = {}
        self._headers[ 'User-Agent' ]   = 'mustaine/' + __version__
        self._headers[ 'Content-Type' ] = 'application/x-hessian'

        # Parse the uri
        self._uri = urlparse( service_uri )

        if self._uri.scheme == 'http':
            self._factory = None

        elif self._uri.scheme == 'https':
            self._factory = CtxFactory( key_file  = key_file,
                                        cert_file = cert_file )
        else:
            raise NotImplementedError( 'AsyncHessianProxy only supports ' + \
                                       'http:// and https:// URIs' )

        # autofill credentials if they were passed via url instead of kwargs
        if ( self._uri.username and self._uri.password ) and not credentials:
            credentials = ( self._uri.username, self._uri.password )

        if credentials:
            auth = 'Basic ' + base64.b64encode(':'.join(credentials))
            self._headers[ 'Authorization' ] = auth

        # Prepare a parser
        self._parser  = Parser()
        self._timeout = timeout

    class __AutoMethod(object):
        # dark magic for autoloading methods
        def __init__(self, caller, method):
            self.__caller = caller
            self.__method = method

        def __call__(self, *args):
            return self.__caller(self.__method, args)

    def __getattr__(self, method):
        return self.__AutoMethod(self, method)

    def __repr__(self):
        return "<mustaine.client.AsyncHessianProxy(\"{url}\")>".format(
                                                      url = self._uri.geturl())

    def __str__(self):
        return self.__repr__()

    def __call__( self, method, args ):
        try:
            request = encode_object( Call( method, args ) )
            self._headers[ 'Content-Length'] = str(len(request))

            uri = self._uri.geturl()

            deferred = getPage( uri,
                                contextFactory = self._factory,
                                headers  = self._headers,
                                method   = 'POST',
                                postdata = request,
                                timeout  = self._timeout )

            deferred.addCallback( self.parse_response )

        except Exception, exp:
            deferred = Deferred()
            deferred.errback( exp )

        return deferred

    def parse_response( self, response ):

        if len( response ) == 0:
            raise ProtocolError( self._uri.geturl(), 'FATAL:',
                                 'Server sent zero-length response' )


        # Parse the response
        reply = self._parser.parse_string( response )

        if isinstance( reply.value, Fault ):
            raise reply.value
        else:
            return reply.value

