"""
Cinelab serializer implementation.
"""
import base64
from bisect import insort
from json import dump, loads

from libadvene.model.cam.consts import CAM_NS_PREFIX, CAM_TYPE, CAMSYS_TYPE
import libadvene.model.cam.util.bookkeeping as bk
from libadvene.model.cam.util.bookkeeping import iter_filtered_meta_ids
from libadvene.model.consts import DC_NS_PREFIX
from libadvene.model.core.media import FOREF_PREFIX
from libadvene.model.serializers.advene_xml import DEFAULTS, split_uri_ref
from libadvene.model.serializers.unserialized import \
    iter_unserialized_meta_prefix

NAME = "Cinelab Advene Json"

EXTENSION = ".cjp" # Cinelab Json Package

MIMETYPE = "application/x-cinelab-package+json"

def make_serializer(package, file_):
    """Return a serializer that will serialize `package` to `file_`.

    `file_` is a writable file-like object. It is the responsibility of the
    caller to close it.

    The returned object must implement the interface for which
    :class:`advene_xml._Serializer` is the reference implementation.
    """
    return _Serializer(package, file_)

def serialize_to(package, file_):
    """A shortcut for ``make_serializer(package, file_).serialize()``.

    NB: `_standalone_xml` is an internal parameter which is not part of the
    public interface of serializers.

    See also `make_serializer`.
    """
    return _Serializer(package, file_).serialize()


class _Serializer(object):

    def serialize(self):
        """Perform the actual serialization."""
        self.prepare_json()
        dump(self.json, self.file, check_circular=False, indent=1)

    # end of the public interface of Serializer

    def prepare_json(self):
        """Serializes into dict self.json, but not in the given file."""

        package = self.package
        self.namespaces = package._get_namespaces_as_dict()
        root = self.json = { "format": "http://advene.org/ns/cinelab/" }
        context = dict( (v, k) for k, v in self.namespaces.items() )
        if context:
            root["@context"] = context
        uri = package.uri
        if uri:
            root["@"] = uri
        root["imports"] = [ self._serialize_import(i)
                            for i in package.own.imports ]
        root["annotation_types"] = [ self._serialize_tag(i)
                                     for i in package.own.annotation_types ]
        root["relation_types"] = [ self._serialize_tag(i)
                                   for i in package.own.relation_types ]
        root["tags"] = [ self._serialize_tag(i)
                         for i in package.own.user_tags ]
        root["medias"] = [ self._serialize_media(i)
                           for i in package.own.medias ]
        root["resources"] = [ self._serialize_resource(i)
                              for i in package.own.resources ]
        root["annotations"] = [ self._serialize_annotation(i)
                                for i in package.own.annotations ]
        root["relations"] = [ self._serialize_relation(i)
                              for i in package.own.relations ]
        root["views"] = [ self._serialize_resource(i)
                          for i in package.own.views ]
        root["queries"] = [ self._serialize_resource(i)
                            for i in package.own.queries ]
        root["schemas"] = [ self._serialize_list(i)
                            for i in package.own.schemas ]
        root["lists"] = [ self._serialize_list(i)
                          for i in package.own.user_lists ]
        root["meta"] = self._serialize_meta(package)
        root["tagging"] = self._serialize_external_tagging()

        _clean_json(root)        

    def __init__(self, package, file_):

        # this will be ugly, because ElementTree in python 2.5 does not handle
        # custom namespace prefix, so we just handle them ourselves

        self.package = package
        self.namespaces = {}
        self.json = None
        self.file = file_
        self.unserialized_meta_prefixes = list(iter_unserialized_meta_prefix())
        insort(self.unserialized_meta_prefixes, CAM_TYPE)
        insort(self.unserialized_meta_prefixes, CAMSYS_TYPE)
        self.unserialized_meta_prefixes.append(None)

    # element serializers

    def _serialize_media(self, m):
        ret = { "id": m.id, "url": m.url }
        foref = m.frame_of_reference
        if foref.startswith(FOREF_PREFIX):
            if m.unit != DEFAULTS["media@unit"]:
                ret["unit"] = str(m.unit)
            if m.origin != DEFAULTS["media@origin"]:
                ret["origin"] = str(m.origin)
        else:
            ret["frame_of_reference"] = foref
        ret["tags"] = self._serialize_element_tags(m)
        ret["meta"] = self._serialize_meta(m)
        _clean_json(ret)
        return ret

    def _serialize_annotation(self, a):
        mid = a.media_id
        tid = a.get_meta_id(CAM_TYPE, None)
        ret = { "id": a.id, "media": mid, "begin": a.begin, "end": a.end,
                "type": tid}
        ret["content"] = self._serialize_content(a)
        ret["tags"] = self._serialize_element_tags(a)
        ret["meta"] = self._serialize_meta(a)
        # IRI Misinterpretation
        if a.content_mimetype == "application/x-ldt-structured":
            ret["meta"]["id-ref"] = tid
        _clean_json(ret)
        return ret

    def _serialize_relation(self, r):
        tid = r.get_meta_id(CAM_TYPE, None)
        ret = { "id": r.id, "type": tid }
        ret["members"] = list(r.iter_member_ids())
        ret["content"] = self._serialize_content(r)
        ret["tags"] = self._serialize_element_tags(r)
        ret["meta"] = self._serialize_meta(r)
        _clean_json(ret)
        return ret

    def _serialize_list(self, L):
        ret = { "id": L.id }
        ret["items"] = list(L.iter_item_ids())
        ret["tags"] = self._serialize_element_tags(L)
        ret["meta"] = self._serialize_meta(L)
        _clean_json(ret)
        return ret

    def _serialize_tag(self, t):
        ret = { "id": t.id }
        tagged_elements = t.iter_element_ids(self.package, False)
        ret["imported_elements"] = [ id_ for id_ in tagged_elements
                                     if id_.find(":") > 0 ]
        ret["tags"] = self._serialize_element_tags(t)
        ret["meta"] = self._serialize_meta(t)
        _clean_json(ret)
        return ret

    def _serialize_resource(self, r):
        ret = { "id": r.id }
        ret["content"] = self._serialize_content(r)
        ret["tags"] = self._serialize_element_tags(r)
        ret["meta"] = self._serialize_meta(r)
        _clean_json(ret)
        return ret

    def _serialize_import(self, i):
        ret = { "id": i.id, "url": i.url, "uri": i.uri }
        ret["tags"] = self._serialize_element_tags(i)
        ret["meta"] = self._serialize_meta(i)
        _clean_json(ret)
        return ret

    # common methods

    def _serialize_content(self, elt):
        mimetype = elt.content_mimetype
        if mimetype == "x-advene/none":
            return None
        if mimetype == "application/x-ldt-structured":
            # IRI Misinterpretation
            ret = elt.content_parsed
            ret["mimetype"] = mimetype
            return ret

        ret = {}
        if mimetype != DEFAULTS["content@mimetype"]:
            ret["mimetype"] = mimetype
        ret["model"] = elt.content_model_id

        url = elt.content_url
        is_link = (url and url[:9] != 'packaged:')
        if is_link:
            ret["url"] = url
        else:
            data = elt.content_data
            if mimetype == "application/json" or mimetype[-5:] == "+json":
                # try to serialize Json data as Json object
                try:
                    data = loads(data)
                except ValueError:
                    pass
            elif not elt.content_is_textual and len(data):
                data = base64.encodestring(data)
                ret["encoding"] = "base64"
            ret["data"] = data

        _clean_json(ret)
        return ret

    def _serialize_meta(self, obj):
        """
        Transform pairs in a Json-friendly form.

        Assumes that pairs is sorted according to the first component (key).
        """
        ret = {}
        umps = iter(self.unserialized_meta_prefixes)
        ump = umps.next()

        for k, v in iter_filtered_meta_ids(obj):
            while ump and k >= ump:
                if k.startswith(ump):
                    k = None # used below to continue outer loop
                    break
                else:
                    ump = umps.next()
            if k is None:
                continue

            ns, tag = split_uri_ref(k)
            if (ns == DC_NS_PREFIX and tag in UNPREFIXED_DC) \
            or ns == CAM_NS_PREFIX:
                k = tag.replace("-", "_")
            else:
                prefix = self.namespaces.get(ns)
                if prefix is not None:
                    k = "%s:%s" % (prefix, tag)
            if v.is_id:
                v = { "id_ref": v }

            ret[k] = v

        return ret

    def _serialize_element_tags(self, elt):
        return list(elt.iter_my_user_tag_ids(self.package, inherited=False))

    def _serialize_external_tagging(self):
        return [ { "element": pair[0], "tag": pair[1] } for pair in
                 self.package._backend.iter_external_tagging(self.package._id)
                 ]

def _clean_json(obj):
    todelete = [ key for key, val in obj.items() if not val
                 and val != 0 and key != "data" ]
    for key in todelete:
        del obj[key]

UNPREFIXED_DC = frozenset(["creator", "created", "contributor", "modified",
                           "description", "title"])
