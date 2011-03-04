"""
I am the content handler for a set of mimetypes using attribute-value pairs.
"""
from sys import stderr
import urllib

# general handler interface

MIMETYPES = [
        "application/x-advene-builtin-view",
        "application/x-advene-type-constraint",
        'application/x-advene-structured',
]

def claims_for_handle(mimetype):
    """Is this content likely to handle a content with that mimetype.

    Return an int between 00 and 99, indicating the likelyhood of this handler
    to handle correctly the given mimetype. 70 is used as a standard value when
    the hanlder is pretty sure it can handle the mimetype.
    """
    if mimetype in MIMETYPES:
        return 99
    else:
        return 0

def parse_content(obj):
    """
    Parse the content of the given package element, and return the produced
    object.
    """
    r = {}
    unparsed = u""
    for l in obj.content_data.splitlines():
        if not l:
            continue
        if '=' in l:
            key, val = l.split("=", 1)
            key = key.strip()
            val = val.strip()
            r[key] = urllib.unquote(val.encode("utf8")).decode("utf8")
        else:
            unparsed += l
    if unparsed:
        r["_error"] = unparsed
    return r

def unparse_content(obj):
    """
    Serializes (or unparse) an object produced by `parse_content` into a
    string.
    """
    r = ""
    for k,v in obj.iteritems():
        r += u"%s = %s\n" % (k, quote(v))
    return r

def quote(v):
    """Poor man's urllib.quote.
    
    It should preserve the readability of the content while being compatible
    with RFC2396 when decoding.
    """
    return v.replace('\n', '%0A').replace('=', '%3D').replace('%', '%25')
