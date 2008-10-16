"""
I define the class of annotations.
"""

import itertools

from advene.model.consts import _RAISE
from advene.model.core.element import PackageElement, ElementCollection, \
                                      ANNOTATION, MEDIA, RESOURCE, RELATION
from advene.model.core.content import WithContentMixin
from advene.model.tales import tales_property, tales_use_as_context
from advene.util.autoproperty import autoproperty
from advene.util.session import session


class Annotation(PackageElement, WithContentMixin):
    """FIXME: missing docstring.
    """

    ADVENE_TYPE = ANNOTATION

    # attributes that do not prevent annotations to be volatile
    _begin = None
    _end = None
    _media_id = None
    _media = None

    @classmethod
    def instantiate(cls, owner, id,
                    media, begin, end, mimetype, model, url, *args):
        """
        Factory method to create an instance based on backend data.
        """
        r = super(Annotation, cls).instantiate(
                    owner, id, media, begin, end, mimetype, model, url, *args)
        r._begin = begin
        r._end = end
        r._media_id = media
        r._media = None
        r._instantiate_content(mimetype, model, url)
        return r

    @classmethod
    def create_new(cls, owner, id,
                   media, begin, end, mimetype, model, url):
        """
        Factory method to create a new instance both in memory and backend.
        """
        media_id = PackageElement._check_reference(owner, media, MEDIA, True)
        begin = int(begin)
        end = int(end)
        model_id = PackageElement._check_reference(owner, model, RESOURCE)
        cls._check_content_cls(mimetype, model_id, url)
        owner._backend.create_annotation(owner._id, id, media_id, begin, end,
                                         mimetype, model_id, url)
        r = cls.instantiate(owner, id, media_id, begin, end,
                            mimetype, model_id, url)
        if media is not media_id:
            # we have the instance, let's cache it now
            r._media = media
        return r

    def _update_caches(self, old_idref, new_idref, element, relation):
        """
        :see-also: `advene.model.core.element.PackageElement._update_caches`
        """
        if relation == ("media"):
            self._media_id = new_idref
        else:
            super(Annotation, self) \
                ._update_caches(old_idref, new_idref, element, relation)

    def __str__(self):
        return "Annotation(%s,%s,%s)" % \
               (self._media_id, self._begin, self._end)

    def _cmp(self, other):
        """
        Common implementation for __lt__, __gt__, __le__ and __ge__.

        Do not rename it to __cmp__ because it would be used for __eq__ as
        well, which is not what we want.
        """
        return self._begin - other._begin \
            or self._end - other._end \
            or cmp(self._media_id, other._media_id)

    def __lt__(self, other):
        return getattr(other, "ADVENE_TYPE", None) is ANNOTATION \
           and self._cmp(other) < 0

    def __le__(self, other):
        return getattr(other, "ADVENE_TYPE", None) is ANNOTATION \
           and self._cmp(other) <= 0

    def __gt__(self, other):
        return getattr(other, "ADVENE_TYPE", None) is ANNOTATION \
           and self._cmp(other) > 0

    def __ge__(self, other):
        return getattr(other, "ADVENE_TYPE", None) is ANNOTATION \
           and self._cmp(other) >= 0

    def __contains__(self, other):
        if type(self) == type(other):
            return self.begin <= other.begin and other.end <= self.end
        else:
            o = long(other)
            return self._begin <= other <= self._end

    def get_media(self, default=None):
        """Return the media associated to this annotation.

        If the media is unreachable, the ``default`` value is returned.

        See also `media` and `media_id`.
        """
        r = self._media
        if r is None:
            r = self._media = \
                self._owner.get_element(self._media_id, default)
        return r

    @autoproperty
    def _get_media(self):
        """Return the media associated to this annotation.

        If the media instance is unreachable, an exception is raised.

        See also `get_media` and `media_id`.
        """
        return self.get_media(_RAISE)

    @autoproperty
    def _set_media(self, media):
        mid = self._check_reference(self._owner, media, MEDIA, True)
        self.emit("pre-modified::media", "media", media)
        self._media_id = mid
        self._media = media
        self.__store()
        self.emit("modified::media", "media", media)

    @autoproperty
    def _get_media_id(self):
        """The id-ref of this annotation's media.

        This is a read-only property giving the id-ref of the resource held
        by `media`.

        Note that this property is accessible even if the corresponding
        media is unreachable.

        See also `get_media` and `media`.
        """
        return self._media_id

    @autoproperty
    def _get_begin(self):
        return self._begin

    @autoproperty
    def _set_begin(self, val):
        self.emit("pre-modified::begin", "begin", val)
        self._begin = val
        self.__store()
        self.emit("modified::begin", "begin", val)

    @autoproperty
    def _get_end(self):
        return self._end

    @autoproperty
    def _set_end(self, val):
        self.emit("pre-modified::end", "end", val)
        self._end = val
        self.__store()
        self.emit("modified::end", "end", val)

    @autoproperty
    def _get_duration(self):
        """The duration of this annotation.

        This property is a shortcut for ``self.end - self.begin``. Setting it
        will update self.end accordingly, leaving self.begin unmodified.
        return self._end - self._begin.

        This property will also be modified by setting self.begin or self.end,
        since each one of these properties leaves the other one unmodified when set.
        """
        return self._end - self._begin

    @autoproperty
    def _set_duration(self, val):
        self._set_end(self._begin + val)

    def __store(self):
        o = self._owner
        o._backend.update_annotation(o._id, self._id,
                                     self._media_id, self._begin, self._end)

    # relation management shortcuts

    def iter_relations(self, package=None, position=None, inherited=True):
        """
        Iter over all the relations involving this annotation, from the point of
        view of `package`.

        If `position` is provided, only the relation where this annotations is
        in the given position are yielded.

        If `inherited` is True (default), all the relations imported by the
        package are searched, else only proper relations of the package are
        searched.

        If ``package`` is not provided, the ``package`` session variable is
        used. If the latter is unset, a TypeError is raised.
        """
        if package is None:
            package = session.package
        if package is None:
            raise TypeError("no package set in session, must be specified")
        if inherited:
            g = package.all
        else:
            g = package.own
        return g.iter_relations(member=self, position=position)

    def count_relations(self, package=None, position=None):
        """
        Count all the relations involving this annotation, from the point of
        view of `package`.

        If `position` is providsed, only the relation where this annotations is
        in the given position are counted.

        If ``package`` is not provided, the ``package`` session variable is
        used. If the latter is unset, a TypeError is raised.
        """
        if package is None:
            package = session.package
        if package is None:
            raise TypeError("no package set in session, must be specified")
        return package.all.count_relations(member=self, position=position)

    @property
    def relations(annotation):
        class AnnotationRelations(ElementCollection):
            __iter__ = annotation.iter_relations
            __len__ = annotation.count_relations
            def __contains__(self, r):
                return getattr(r, "ADVENE_TYPE", None) == RELATION \
                   and annotation in r
        return AnnotationRelations(session.package)

    @property
    def incoming_relations(self):
        """List of incoming relations.
        """
        return self.relations.filter(position=0)

    @property
    def outgoing_relations(self):
        """List of outgoing relations.
        """
        return self.relations.filter(position=1)

    @property
    def related(self):
        """List (iterator) of related annotations
        """
        return itertools.chain(
            (r[1] for r in self.incoming_relations),
            (r[0] for r in self.outgoing_relations)
            )

    @property
    def typed_related_in(self):
        """List of tuples (relation type, list of related incoming annotations)
        """
        return [ (at, [r[1] for r in l]) for (at, l) in 
                 itertools.groupby(self.incoming_relations, key=lambda e: e.type) ]

    @property
    def typed_related_out(self):
        """List of tuples (relation type, list of related outgoing annotations)
        """
        return [ (at, [r[0] for r in l]) for (at, l) in 
                 itertools.groupby(self.outgoing_relations, key=lambda e: e.type) ]

    @tales_property
    @tales_use_as_context("package")
    def _tales_relations(annotation, context_package):
        p = context_package
        class TalesAnnotationRelations(ElementCollection):
            def __iter__(self, position=None):
                return annotation.iter_relations(p, position)
            def __len__(self, position=None):
                return annotation.count_relations(p, position)
            def __contains__(self, r):
                return getattr(r, "ADVENE_TYPE", None) == RELATION \
                   and annotation in r
        return TalesAnnotationRelations(p)

    @tales_property
    def _tales_incoming_relations(self, context):
        return self._tales_relations(context).filter(position=0)

    @tales_property
    def _tales_outgoing_relations(self, context):
        return self._tales_relations(context).filter(position=1)

    @tales_property
    def _tales_typed_related_in(self, context):
        """Dictionary of tuples (relation type id, list of related incoming annotations)
        """
        return dict( (at.id, r) for (at, r) in self.typed_related_in )

    @tales_property
    def _tales_typed_related_out(self, context):
        """Dictionary of tuples (relation type id, list of related outgoing annotations)
        """
        return dict( (at.id, r) for (at, r) in self.typed_related_out )

    @tales_property
    def _tales_snapshot_url(self, context):
        options=context.globals['options']
        controller=options['controller']
        if controller.server is not None:
            url=controller.server.urlbase
        else:
            url='/'
        url=url +  "packages/%s/imagecache/%s/%d" % (options['aliases'][self.owner],
                                                     self.media.id,
                                                     self.begin)
        return url

    @tales_property
    def _tales_player_url(self, context):
        options=context.globals['options']
        controller=options['controller']
        if controller.server is not None:
            url=controller.server.urlbase
        else:
            url='/'
        url=url +  "media/%s/play/%d" % (self.media.id,
                                         self.begin)
        return url
