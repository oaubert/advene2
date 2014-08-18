import libadvene.model.serializers.advene_xml as advene_xml_serializer
import libadvene.model.serializers.advene_zip as advene_zip_serializer
import libadvene.model.serializers.cinelab_json as cinelab_json_serializer
import libadvene.model.serializers.cinelab_xml as cinelab_xml_serializer
import libadvene.model.serializers.cinelab_zip as cinelab_zip_serializer
try:
    import rdflib
    import libadvene.model.serializers.cinelab_rdf as cinelab_rdf_serializer
    import libadvene.model.serializers.cinelab_ttl as cinelab_ttl_serializer
except ImportError:
    rdflib = None
    from warnings import warn
    warn("rdflib not available, could not register RDF serializers")

# serializer register functions

def iter_serializers():
    global _serializers
    return iter(_serializers)

def register_serializer(b):
    global _serializers
    _serializers.insert(0, b)

def unregister_serializer(b):
    global _serializers
    _serializers.remove(b)

# implementation

_serializers = []

# default registrations

register_serializer(advene_xml_serializer)
register_serializer(advene_zip_serializer)
register_serializer(cinelab_json_serializer)
register_serializer(cinelab_xml_serializer)
register_serializer(cinelab_zip_serializer)
if rdflib:
    register_serializer(cinelab_rdf_serializer)
    register_serializer(cinelab_ttl_serializer)
