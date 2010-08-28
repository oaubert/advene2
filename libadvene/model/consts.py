"""I define constants used all over the `libadvene.model` package."""

ADVENE_NS_PREFIX = "http://advene.org/ns/"

# useful meta prefixes
PARSER_META_PREFIX = "%s%s" % (ADVENE_NS_PREFIX, "parser-meta#")
DC_NS_PREFIX = "http://purl.org/dc/elements/1.1/"
RDFS_NS_PREFIX = "http://www.w3.org/2000/01/rdf-schema#"

# other advene-related namespace URIs
ADVENE_XML = "%s%s" % (ADVENE_NS_PREFIX, "advene-xml/")

# common metadata

PACKAGED_ROOT = "%spackage_root" % PARSER_META_PREFIX

# implementation-related constant
# used as the ``default`` parameter to specify that an exception should be
# raised on default
_RAISE = object()
