"""
I am the content handler for application/x-advene-values
"""

# general handler interface

def claims_for_handle(mimetype):
    """Is this content likely to handle a content with that mimetype.

    Return an int between 00 and 99, indicating the likelyhood of this handler
    to handle correctly the given mimetype. 70 is used as a standard value when
    the hanlder is pretty sure it can handle the mimetype.
    """
    if mimetype == "application/x-advene-values":
        return 99
    else:
        return 0

def parse_content(obj):
    """Parse the content of the given package element, and return the produced object.
    """
    def convert(v):
        try:
            r=float(v)
        except ValueError:
            r=0
        return r
    return [ convert(v) for v in obj.content_data.split() ]

def unparse_content(obj):
    """Serializes (or unparse) an object produced by `parse_content` into a string.
    """
    return " ".join( str(v) for v in obj )
