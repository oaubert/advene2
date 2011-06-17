from warnings import warn

from libadvene.model.cam.consts import CAMSYS_TYPE, CAM_NS_PREFIX
from libadvene.model.cam.element import CamElementMixin
from libadvene.model.cam.exceptions import LikelyMistake
from libadvene.model.cam.group import CamGroupMixin
from libadvene.model.core.element import LIST, RESOURCE, ElementCollection
from libadvene.model.core.tag import Tag as CoreTag
from libadvene.model.tales import tales_property, tales_use_as_context
from libadvene.model.view.type_constraint import apply_to
from libadvene.util.alias import alias
from libadvene.util.autoproperty import autoproperty
from libadvene.util.session import session


CAM_CONTENT_MIMETYPE = CAM_NS_PREFIX + "content-mimetype"
CAM_CONTENT_MODEL = CAM_NS_PREFIX + "content-model"
CAM_ELEMENT_CONSTRAINT = CAM_NS_PREFIX + "element-constraint"

class Tag(CoreTag, CamElementMixin, CamGroupMixin):

    @classmethod
    def instantiate(cls, owner, id, *args):
        r = super(Tag, cls).instantiate(owner, id, *args)
        r._transtype()
        return r

    def _set_camsys_type(self, value, val_is_idref=False):
        super(Tag, self)._set_camsys_type(value, val_is_idref)
        self._transtype(value)

    def _transtype(self, systype=None):
        """
        Transtypes this Tag to the appropriate subclass according to the given
        systype (assumed to be the current or future systype).

        If systype is omitted, it is retrieved from the metadata.
        """
        if systype is None:
            systype = self.get_meta(CAMSYS_TYPE, None)
        if systype == "annotation-type":
            newtype = AnnotationType
        elif systype == "relation-type":
            newtype = RelationType
        else:
            newtype = Tag
        if self.__class__ is not newtype:
            self.__class__ = newtype


class CamTypeMixin(object):
    """
    Implement features common to annotation and relation types.

    That includes shortcut attributes to the underlying type-constraint,
    and access to the schemas containing the type.
    """

    # constraint related

    def set_meta(self, key, value, val_is_idref=False):
        if key == CAM_CONTENT_MODEL:
            advene_type = getattr(value, "ADVENE_TYPE", None)
            if advene_type is None and not val_is_idref \
            or advene_type is not None and advene_type != RESOURCE:
                raise TypeError("content-model must be a content model")
        elif key == CAM_ELEMENT_CONSTRAINT:
            advene_type = getattr(value, "ADVENE_TYPE", None)
            if advene_type is None and not val_is_idref \
            or advene_type is not None and advene_type != VIEW:
                raise TypeError("element-constraint must be a test view")

        super(CamTypeMixin, self).set_meta(key, value, val_is_idref)

    def check_element(self, e):
        """
        Applies the element_constraint to the given element and returns the
        result.
        """
        my_view = {}
        if self.content_mimetype is not None:
            my_view["mimetype"] = self.content_mimetype
        if self.content_model is not None:
            my_view["model"] = self.content_model

        if self.element_constraint is not None:
            ret = self.element_constraint.apply_to(e)
        else:
            ret = True
        return ret & apply_to(my_view, e)

    def check_all(self, package=None, _true=lambda *a: True):
        """
        Applies the element_constraint to all the elements in the given
        package (session.package) if None, and return the aggregated result.
        """
        if self.element_constraint:
            check1 = self.element_constraint.apply_to
        else:
            check1 = _true

        my_view = {}
        if self.content_mimetype is not None:
            my_view["mimetype"] = self.content_mimetype
        if self.content_model is not None:
            my_view["model"] = self.content_model
        if my_view:
            check2 = lambda e: apply_to(my_view, e)
        else:
            check2 = _true

        r = True
        for e in self.iter_elements(package):
            r = r & check1(e) & check2(e)
        return r

    # schema related

    def iter_my_schemas(self, package=None, inherited=True):
        if package is None:
            package = session.package
        if package is None:
            raise TypeError("no package set in session, must be specified")
        if inherited:
            g = package.all
        else:
            g = package.own
        return g.iter_schemas(item=self)

    def count_my_schemas(self, package=None, inherited=True):
        if package is None:
            package = session.package
        if package is None:
            raise TypeError("no package set in session, must be specified")
        if inherited:
            g = package.all
        else:
            g = package.own
        return g.count_schemas(item=self)

    @autoproperty
    def _get_my_schemas(type_, package=None):
        """
        Return an ElementCollection of all the schemas containing this type.

        In python, property `my_schemas` uses ``session.package``.
        In TALES, property `my_schemas` uses ``package``.
        """
        if package is None:
            package = session.package
            if package is None:
                raise TypeError("no package set in session, must be specified")
        class TypeSchemas(ElementCollection):
            def __iter__(self):
                return type_.iter_my_schemas(package)
            def __len__(self):
                return type_.count_my_schemas(package)
            def __contains__(self, s):
                return getattr(s, "ADVENE_TYPE", None) == LIST \
                   and s.get_meta(CAMSYS_TYPE, None) == "schema" \
                   and type_ in s
        return TypeSchemas(package)

    def iter_schemas(self):
        """
        Raise a warning, as this is probably not what the user wants to do.

        This method iter over all schemas *tagged* with self; with an
        Annotation type / Relation type, it is more likely the user wanted to
        call iter_my_schemas.
        """
        warn("you may actually mean .my_schemas", LikelyMistake)
        return super(CamTypeMixin, self).iter_schemas()

    @tales_property
    @tales_use_as_context("package")
    @alias(_get_my_schemas)
    def _tales_my_schemas(self, context):
        # recycle _get_my_schemas implementation
        pass


class AnnotationType(CamTypeMixin, Tag):
    """
    The class of annotation types.
    """
    # This class is automatically transtyped from Tag (and back) when
    # CAMSYS_TYPE is modified. See Tag.set_meta
    pass

class RelationType(CamTypeMixin, Tag):
    """
    The class of relation types.
    """
    # This class is automatically transtyped from Tag (and back) when
    # CAMSYS_TYPE is modified. See Tag.set_meta
    pass

Tag.make_metadata_property(CAMSYS_TYPE, "system_type", default=None)
Tag.make_metadata_property(CAM_NS_PREFIX + "representation", default=None)
Tag.make_metadata_property(CAM_NS_PREFIX + "color", default=None)
Tag.make_metadata_property(CAM_NS_PREFIX + "element-color",
                           "element_color", default=None)
Tag.make_metadata_property(CAM_ELEMENT_CONSTRAINT,
                           "element_constraint", default=None)
Tag.make_metadata_property(CAM_CONTENT_MIMETYPE,
                           "content_mimetype", default=None)
Tag.make_metadata_property(CAM_CONTENT_MODEL,
                           "content_model", default=None)

def _create_type_constraint(type_elt):
    """
    TODO: is this still used?
    """
    prefix = ":constraint"
    if type_elt._id[0] != ":":
        prefix += ":"
    c = self.create_view(
            "%s%s" % (prefix, type_elt._id),
            "application/x-advene-type-constraint",
    )
    type_elt.enter_no_event_section()
    try:
        type_elt.element_constraint = c
    finally:
        type_elt.exit_no_event_section()
