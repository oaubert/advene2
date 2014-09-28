"""
Cinelab parser implementation.
"""

from libadvene.model.cam.consts import CAM_NS_PREFIX, CAM_XML
from libadvene.model.cam.util.bookkeeping import inherit_bk_metadata
from libadvene.model.consts import DC_NS_PREFIX, PARSER_META_PREFIX
from libadvene.model.core.media import FOREF_PREFIX
from libadvene.model.parsers.exceptions import ParserError
import libadvene.model.serializers.cinelab_json as serializer
from libadvene.model.serializers.cinelab_json import UNPREFIXED_DC
from libadvene.util.files import get_path

import base64
from json import load, dumps
import re

class Parser(object):

    NAME = serializer.NAME
    EXTENSION = serializer.EXTENSION
    MIMETYPE = serializer.MIMETYPE
    DEFAULTS = serializer.DEFAULTS
    SERIALIZER = serializer # may be None for some parsers

    _NAMESPACE_URI = CAM_XML

    @classmethod
    def claims_for_parse(cls, file_):
        """Is this parser likely to parse that file-like object?

        `file_` is a readable file-like object. It is the responsability of the
        caller to close it.

        Return an int between 00 and 99, indicating the likelyhood of this
        parser to handle correctly the given URL. 70 is used as a standard
        value when the parser is pretty sure it can handle the URL.
        """
        r = 0
        info = getattr(file_, "info", lambda: {})()
        mimetype = info.get("content-type", "")
        if mimetype.startswith(cls.MIMETYPE):
            r = 80
        else:
            if mimetype.startswith("application/json") \
            or mimetype.startswith("text/javascript"):
                r += 20
            fpath = get_path(file_)
            if fpath.endswith(cls.EXTENSION):
                r += 50
            elif fpath.endswith(".json"):
                r += 20
            elif fpath.endswith(".js"):
                r += 10

        return r

    @classmethod
    def make_parser(cls, file_or_json, package):
        """Return a parser that will parse `file_` into `package`.

        `file_or_json` is either
        - a writable file-like object
          (it is then the responsability of the caller to close it), or
        - a JSON object

        The returned object must implement the interface for which
        :class:`_Parser` is the reference implementation.
        """
        return cls(file_or_json, package)

    @classmethod
    def parse_into(cls, file_or_json, package):
        """A shortcut for ``make_parser(file_or_json, package).parse()``.

        See also `make_parser`.
        """
        cls(file_or_json, package).parse()

    def parse(self):
        "Do the actual parsing."
        package = self.package
        file_or_json = self.file_or_json
        if hasattr(file_or_json, "read"):
            json = load(file_or_json)
        else:
            json = file_or_json
        package.enter_no_event_section()
        context = json.get("@context")
        if context:
            package.set_meta(PARSER_META_PREFIX+"namespaces",
                             "\n".join("%s %s" % i for i in context.items()))
            self.namespaces = context
        uri = json.get("@")
        if uri:
            package.uri = uri
        try:
            for npass in (1, 2):
                for i in json.get("imports", ()):
                    self._parse_import(i, package, npass)
                for i in json.get("resources", ()):
                    self._parse_simple(i, package, npass, "resource")
                for i in json.get("tags", ()):
                    self._parse_tag(i, package, npass, "user_tag")
                for i in json.get("annotation_types", json.get("annotation-types", ())):
                    self._parse_tag(i, package, npass, "annotation_type")
                for i in json.get("relation_types", json.get("relation-types", ())):
                    self._parse_tag(i, package, npass, "relation_type")
                for i in json.get("medias", ()):
                    self._parse_media(i, package, npass)
                for i in json.get("annotations", ()):
                    self._parse_annotation(i, package, npass)
                for i in json.get("relations", ()):
                    self._parse_relation(i, package, npass)
                for i in json.get("views", ()):
                    self._parse_simple(i, package, npass, "view")
                for i in json.get("queries", ()):
                    self._parse_simple(i, package, npass, "query")
                for i in json.get("lists", ()):
                    self._parse_list(i, package, npass, "user_list")
                for i in json.get("schemas", ()):
                    self._parse_list(i, package, npass, "schema")
                if npass == 1:
                    self._parse_meta(json, package, package)
                    # required to inherit bookkeeping metadata in elements
            for i in json.get("tagging", ()):
                self._parse_tagging(i, package)
        finally:
            package.exit_no_event_section()

    # end of public interface

    def __init__(self, file_or_json, package):
        self.file_or_json = file_or_json
        self.package = package
        self.namespaces = {}

    # NB: most of the following parsing methods have two passes;
    # * in pass 1, objects are only created; this prevents the creation of
    # forward references;
    # * in pass 2, content, metadata and subelements are added, possibly
    # with reference to other objects created in pass 1

    def _parse_pass2(self, json, pkg, *additional_methods):
        elt = pkg[json["id"]]
        elt.enter_no_event_section()
        try:
            for method in additional_methods:
                method(json, elt, pkg)
            self._parse_tags_on(json, elt, pkg)
            self._parse_meta(json, elt, pkg)
        finally:
            elt.exit_no_event_section()

    def _parse_import(self, json, pkg, npass):
        if npass == 1:
            pkg._create_import_in_parser(json["id"], json["url"],
                                         json.get("uri", ""))
        else:
            self._parse_pass2(json, pkg)

    def _parse_tag(self, json, pkg, npass, kind):
        if npass == 1:
            creator = getattr(pkg, "create_%s" % kind)
            creator(json["id"])
        else:
            self._parse_pass2(json, pkg, self._parse_tag_items)

    def _parse_media(self, json, pkg, npass):
        if npass == 1:
            unit = json.get("unit", self.DEFAULTS["media@unit"])
            origin = json.get("origin", self.DEFAULTS["media@origin"])
            foref = "%s%s;o=%s" % (FOREF_PREFIX, unit, origin)
            pkg.create_media(json["id"], json["url"], foref)
        else:
            self._parse_pass2(json, pkg)

    def _parse_simple(self, json, pkg, npass, kind):
        if npass == 1:
            creator = getattr(pkg, "create_%s" % kind)
            content = json.get("content")
            content_type = (content and content.get("mimetype")
                            or self.DEFAULTS["content@mimetype"])
            creator(json["id"], content_type)
        else:
            self._parse_pass2(json, pkg, self._parse_content)

    def _parse_annotation(self, json, pkg, npass):
        if npass == 1:
            media = json["media"]
            if media.find(":") <= 0: # same package
                media = pkg[media] # already created thanks to parse order
            content = json.get("content")
            content_type = (content and content.get("mimetype")
                            or self.DEFAULTS["content@mimetype"])
            atype = json.get("type", None)
            if atype is None:
                # IRI misinterpretation
                # Maybe we have an old IRI file, which mistook the id-ref attribute for the type information ?
                meta = json.get("meta", None)
                if meta:
                    atype = meta.get("id-ref")
            if atype.find(":") <= 0: # same package
                atype = pkg[atype] # already created thanks to parse order
            pkg.create_annotation(json["id"], media,
                                  json["begin"], json["end"], content_type,
                                  type=atype)
        else:
            self._parse_pass2(json, pkg, self._parse_content)

    def _parse_relation(self, json, pkg, npass):
        if npass == 1:
            content = json.get("content")
            content_type = (content and content.get("mimetype")
                            or self.DEFAULTS["content@mimetype"])
            rtype = json["type"]
            if rtype.find(":") <= 0: # same package
                rtype = pkg[rtype] # already created thanks to parse order
            elt = pkg.create_relation(json["id"], content_type, type=rtype)
            self._parse_items(json, elt, pkg, "members")
            # items are already created thanks to parse order
        else:
            self._parse_pass2(json, pkg, self._parse_content)

    def _parse_list(self, json, pkg, npass, kind):
        if npass == 1:
            creator = getattr(pkg, "create_%s" % kind)
            creator(json["id"])
        else:
            self._parse_pass2(json, pkg, self._parse_items)

    def _parse_tagging(self, json, pkg):
        elt_id = json["element"]
        tag_id = json["tag"]
        # both tag and element should be imported, so no check
        pkg.associate_user_tag(elt_id, tag_id)

    def _parse_tags_on(self, json, elt, pkg):
        tags = json.get("tags")
        if tags is None:
            return
        elt.enter_no_event_section()
        try:
            for tagid in tags:
                if isinstance(tagid, dict):
                    # IRI misinterpretation
                    tagid = tagid.get("id-ref")
                if tagid.find(":") > 0: # imported
                    pkg.associate_user_tag(elt, tagid)
                else:
                    pkg.associate_user_tag(elt, pkg[tagid])
        finally:
            elt.exit_no_event_section()

    def _parse_meta(self, json, elt, pkg):
        meta = json.get("meta")
        if meta:
            for key, val in meta.iteritems():
                if key in UNPREFIXED_DC:
                    key = DC_NS_PREFIX + key
                elif _SUFFIX.match(key):
                    key = CAM_NS_PREFIX + key.replace("_", "-")
                elif _CURIE.match(key):
                    prefix, suffix = key.split(":")
                    key = self.namespaces.get(prefix, prefix+":") + suffix
                if not isinstance(val, dict):
                    elt.set_meta(key, val, False)
                else:
                    val = val.get("id_ref", val.get("id-ref", val))
                    if isinstance(val, dict):
                        # IRI misinterpretation
                        # We could not find an id_ref. Serialize the dict as a string
                        elt.set_meta(key, unicode(val))
                    elif val.find(":") > 0: # imported
                        elt.set_meta(key, val, True)
                    else:
                        elt.set_meta(key, pkg[val])
        if elt is not pkg:
            inherit_bk_metadata(elt, pkg)

    def _parse_tag_items(self, json, elt, pkg):
        for idref in json.get("imported_elements", ()):
            pkg.associate_user_tag(idref, elt)

    def _parse_content(self, json, elt, pkg):
        content = json.get("content")
        if content is None:
            elt.content_mimetype = "x-advene/none"
            return
        mimetype = content.get("mimetype")
        if mimetype:
            elt.content_mimetype = mimetype
        if mimetype == "application/x-ldt-structured":
            # IRI misinterpretation
            del content["mimetype"]
            content = {"data": content}
        model = content.get("model")
        if model and model.find(":") <= 0: # same package
            model = pkg[model]
        if model:
            elt.content_model = model
        url = content.get("url")
        data = content.get("data")
        encoding = content.get("encoding")
        if url:
            if data is not None or encoding:
                raise ParserError("%s: content has both url and data/encoding"
                                  % json["id"])
            elt.content_url = url
        elif data:
            if not isinstance(data, basestring):
                data = dumps(data)
            elif encoding:
                if encoding == "base64":
                    data = base64.decodestring(data)
                else:
                    raise ParserError("encoding %s is not supported", encoding)
            elt.content_data = data

    def _parse_items(self, json, elt, pkg, key="items"):
        items = json.get(key, ())
        elt.enter_no_event_section()
        try:
            for i in items:
                if isinstance(i, dict):
                    # IRI misinterpretation
                    i = i.get("id-ref")
                if i.find(":") <= 0: # same package
                    i = pkg[i]
                elt.append(i)
        finally:
            elt.exit_no_event_section()

#

_SUFFIX = re.compile("^[a-zA-Z_.-]+$")
_CURIE = re.compile("^[a-zA-Z_.-]+:[a-zA-Z_.-]+$")
