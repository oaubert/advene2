"""
Cinelab Turtle serializer implementation.
"""

from libadvene.model.serializers.cinelab_rdf import _Serializer

NAME = "Cinelab Advene Turtle"

EXTENSION = ".ttl" # Cinelab RDF Package

MIMETYPE = "text/turtle"

_FORMAT = "turtle"

def make_serializer(package, file_):
    """Return a serializer that will serialize `package` to `file_`.

    `file_` is a writable file-like object. It is the responsibility of the
    caller to close it.

    The returned object must implement the interface for which
    :class:`advene_xml._Serializer` is the reference implementation.
    """
    return _Serializer(package, file_, _FORMAT)

def serialize_to(package, file_):
    """A shortcut for ``make_serializer(package, file_).serialize()``.

    See also `make_serializer`.
    """
    return _Serializer(package, file_, _FORMAT).serialize()
