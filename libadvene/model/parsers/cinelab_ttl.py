"""
Cinelab Turtle parser implementation.
"""
from libadvene.model.parsers.cinelab_rdf import Parser as RdfParser
import libadvene.model.serializers.cinelab_ttl as serializer


class Parser(RdfParser):

    NAME = serializer.NAME
    EXTENSION = serializer.EXTENSION
    MIMETYPE = serializer.MIMETYPE
    SERIALIZER = serializer # may be None for some parsers

    _FORMAT = "turtle"
