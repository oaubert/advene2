"""
I am the content handler for a set of mimetypes using JSON.
"""

try:
    from json import loads, dumps
except ImportError:
    try:
        from simplejson import loads, dumps
    except ImportError:
        from warnings import warn
        warn("Could not load json nor simplejson - no json support")
        loads = None
        puts = None

# general handler interface

def claims_for_handle(mimetype):
    """Is this content likely to handle a content with that mimetype.

    Return an int between 00 and 99, indicating the likelyhood of this handler
    to handle correctly the given mimetype. 70 is used as a standard value when
    the hanlder is pretty sure it can handle the mimetype.
    """
    if loads is not None and mimetype in [
        "application/json",
    ]:
        return 99
    else:
        return 0

def parse_content(obj):
    """
    Parse the content of the given package element, and return the produced
    object.
    """
    return loads(obj.content_data)

def unparse_content(obj):
    """
    Serializes (or unparse) an object produced by `parse_content` into a
    string.
    """
    return dumps(obj)
