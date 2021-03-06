import libadvene.model.parsers.advene_xml as advene_xml_parser
import libadvene.model.parsers.advene_zip as advene_zip_parser
import libadvene.model.parsers.cinelab_json as cinelab_json_parser
import libadvene.model.parsers.cinelab_xml as cinelab_xml_parser
import libadvene.model.parsers.cinelab_zip as cinelab_zip_parser
try:
    import rdflib
    import libadvene.model.parsers.cinelab_rdf as cinelab_rdf_parser
    import libadvene.model.parsers.cinelab_ttl as cinelab_ttl_parser
except ImportError:
    rdflib = None
    from warnings import warn
    warn("rdflib not available, could not register RDF parsers")


# parser register functions

def iter_parsers():
    global _parsers
    return iter(_parsers)

def register_parser(b):
    global _parsers
    _parsers.insert(0, b)

def unregister_parser(b):
    global _parsers
    _parsers.remove(b)

# implementation

_parsers = []

# default registration

register_parser(advene_xml_parser.Parser)
register_parser(advene_zip_parser.Parser)
register_parser(cinelab_json_parser.Parser)
register_parser(cinelab_xml_parser.Parser)
register_parser(cinelab_zip_parser.Parser)
if rdflib:
    register_parser(cinelab_rdf_parser.Parser)
    register_parser(cinelab_ttl_parser.Parser)
