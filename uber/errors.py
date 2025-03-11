from urllib.parse import quote
from uber.config import c

import cherrypy


class CSRFException(Exception):
    """
    Custom exception to specifically catch CSRF Token errors.
    """


class HTTPRedirect(cherrypy.HTTPRedirect):
    """
    CherryPy uses exceptions to indicate things like HTTP 303 redirects.
    This subclasses the standard CherryPy exception to add string formatting
    and automatic quoting.  So instead of saying::

        raise HTTPRedirect('foo?message={}'.format(quote(bar)))

    we can say::

        raise HTTPRedirect('foo?message={}', bar)

    EXTREMELY IMPORTANT: If you pass in a relative URL, this class will use
    the current querystring to build an absolute URL.  Therefore it's
    EXTREMELY IMPORTANT that the only time you create this class is in the
    context of a pageload.

    Do not save copies this class, only create it on-demand when needed as
    part of a 'raise' statement.
    """
    def __init__(self, page, *args, **kwargs):
        save_location = kwargs.pop('save_location', False)

        args = [self.quote(s) for s in args]
        kwargs = {k: self.quote(v) for k, v in kwargs.items()}
        query = page.format(*args, **kwargs)

        if save_location and cherrypy.request.method == 'GET':
            # Remember the original URI the user was trying to reach.
            # useful if we want to redirect the user back to the same
            # page after they complete an action, such as logging in
            # example URI: '/uber/registration/form?id=786534'
            original_location = cherrypy.request.wsgi_environ['REQUEST_URI']

            # Note: python does have utility functions for this. if this
            # gets any more complex, use the urllib module
            qs_char = '?' if '?' not in query else '&'
            query += '{sep}original_location={loc}'.format(
                sep=qs_char, loc=self.quote(original_location))

        if c.URL_ROOT.startswith("https"):
            cherrypy.request.base = cherrypy.request.base.replace("http://", "https://")
        cherrypy.HTTPRedirect.__init__(self, query)

    def quote(self, s):
        return quote(s) if isinstance(s, str) else str(s)
