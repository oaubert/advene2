"""
I define the class of relations.
"""

from libadvene.model.consts import _RAISE
from libadvene.model.core.element \
  import PackageElement, ANNOTATION, RELATION, RESOURCE
from libadvene.model.core.content import WithContentMixin
from libadvene.model.core.group import GroupMixin

class Relation(PackageElement, WithContentMixin, GroupMixin):
    """
    I expose the protocol of a basic collection, to give access to the members
    of a relation. I also try to efficiently cache the results I know.
    """

    # Caching is performed as follow:
    # __init__ retrieves the number of members, and builds self.__ids
    # and self.__cache, a list of id-refs and instances respectively.
    # Whenever an index is accessed, the member if retrieved from self.__cache.
    # If None, its id-ref is retrieved from self.__ids and the element is
    # retrieved from the package. If the id-ref is None, the id-ref is
    # retrieved from the backend.

    ADVENE_TYPE = RELATION

    # attributes that do not prevent relations to be volatile
    _cache = None
    _ids = None

    @classmethod
    def instantiate(cls, owner, id, mimetype, model, url, *args):
        r = super(Relation, cls). \
                instantiate(owner, id, mimetype, url, model, *args)
        r._instantiate_content(mimetype, model, url)
        c = owner._backend.count_members(owner._id, id)
        r._cache = [None,] * c
        r._ids = [None,] * c
        return r

    @classmethod
    def create_new(cls, owner, id, mimetype, model, url, members=()):
        model_id = PackageElement._check_reference(owner, model, RESOURCE)
        cls._check_content_cls(mimetype, model_id, url, owner)
        owner._backend.create_relation(owner._id, id, mimetype, model_id, url)
        r = cls.instantiate(owner, id, mimetype, model_id, url)
        if members:
            r.extend(members)
        return r

    def _update_caches(self, old_idref, new_idref, element, relation):
        """
        :see-also: `libadvene.model.core.element.PackageElement._update_caches`
        """
        if relation.startswith(":member "):
            index = int(relation[8:])
            self._ids[index] = new_idref
            if element is not None:
                self._cache[index] = element # just in case both were None
        else:
            try:
                super(Relation, self) \
                    ._update_caches(old_idref, new_idref, element, relation)
            except AttributeError:
                pass

    def __len__(self):
        return len(self._cache)

    def __iter__(self):
        """Iter over the members of this relation.

        If the relation contains unreachable members, None is yielded.

        See also `iter_member_ids`.
        """
        for i,m in enumerate(self._cache):
            if m is None:
                m = self.get_member(i, None)
            yield m

    def __getitem__(self, i):
        """Return member with index i, or raise an exception if the item is
        unreachable.

        See also `get_member`  and `get_member_id`.
        """
        if isinstance(i, slice): return self._get_slice(i)
        else: return self.get_member(i, _RAISE)

    def __setitem__(self, i, a):
        if isinstance(i, slice): return self._set_slice(i, a)
        assert getattr(a, "ADVENE_TYPE", None) == ANNOTATION, "A relation member must be an Annotation"
        o = self._owner
        assert o._can_reference(a), "The relation owner %s cannot reference %s" % (str(o), str(a))

        aid = a.make_id_in(o)
        s = slice(i, i+1)
        L = [a,]
        self.emit("pre-modified-items", s, L)
        self._ids[i] = aid
        self._cache[i] = a
        o._backend.update_member(o._id, self._id, aid, i)
        self.emit("modified-items", s, L)

    def __delitem__(self, i):
        if isinstance(i, slice): return self._del_slice(i)
        s = slice(i, i+1)
        self.emit("pre-modified-items", s, [])
        del self._ids[i] # also guarantees that is is a valid index
        del self._cache[i]
        o = self._owner
        o._backend.remove_member(o._id, self._id, i)
        self.emit("modified-items", s, [])

    def _get_slice(self, s):
        c = len(self._cache)
        return [ self.get_member(i, _RAISE) for i in range(c)[s] ]

    def _set_slice(self, s, annotations):
        c = len(self._cache)
        indices = range(c)[s]
        same_length = (len(annotations) == len(indices))
        if s.step is None and not same_length:
            self._del_slice(s)
            insertpoint = s.start or 0
            for a in annotations:
                self.insert(insertpoint, a)
                insertpoint += 1
        else:
            if not same_length:
                raise ValueError("attempt to assign sequence of size %s to "
                                 "extended slice of size %s"
                                 % (len(annotations), len(indices)))
            for i,j in enumerate(indices):
                self.__setitem__(j, annotations[i])

    def _del_slice(self,s):
        c = len(self._cache)
        indices = range(c)[s]
        indices.sort()
        for offset, i in enumerate(indices):
            del self[i-offset]

    def insert(self, i, a):
        # this method accepts a strict id-ref instead of a real element
        o = self._owner
        assert o._can_reference(a), "The relation owner %s cannot reference %s" % (str(o), str(a))
        if hasattr(a, "ADVENE_TYPE"):
            assert a.ADVENE_TYPE == ANNOTATION
            aid = a.make_id_in(o)
        else:
            aid = unicode(a)
            assert aid.find(":") > 0, "Expected *strict* id-ref"
            a = None
        c = len(self._cache)
        if i > c : i = c
        if i < -c: i = 0
        if i < 0 : i += c 
        self._ids.insert(i,aid)
        self._cache.insert(i,a)
        o._backend.insert_member(o._id, self._id, aid, i, c)
        # NB: it is important to pass to the backend the length c computed
        # *before* inserting the member

    def append(self, a):
        # this method accepts a strict id-ref instead of a real element
        o = self._owner
        assert o._can_reference(a), "The relation owner %s cannot reference %s" % (str(o), str(a))
        if hasattr(a, "ADVENE_TYPE"):
            assert a.ADVENE_TYPE == ANNOTATION
            aid = a.make_id_in(o)
        else:
            aid = unicode(a)
            assert aid.find(":") > 0, "Expected *strict* id-ref"
            a = None
        c = len(self._cache)
        s = slice(c,c)
        L = [a,]
        self.emit("pre-modified-items", s, L)
        self._ids.append(aid)
        self._cache.append(a)
        o._backend.insert_member(o._id, self._id, aid, -1, c)
        self.emit("modified-items", s, L)
        # NB: it is important to pass to the backend the length c computed
        # *before* appending the member

    def extend(self, annotations):
        for a in annotations:
            self.append(a)

    def iter_member_ids(self):
        """Iter over the id-refs of the members of this relation.

        See also `__iter__`.
        """
        for i,m in enumerate(self._ids):
            if m is not None:
                yield m
            else:
                yield self.get_member_id(i)

    def get_member(self, i, default=None):
        """Return element with index i, or default if it can not be retrieved.

        The difference with self[i] is that, if the member is unreachable,
        None is returned (or whatever value is passed as ``default``).

        Note that if ``i`` is an invalid index, an IndexError will still be
        raised.

        See also `__getitem__`  and `get_member_id`.
        """
        # NB: internally, default can be passed _RAISE to force exceptions
        assert isinstance(i, (int, long)), "The index must be an integer"
        r = self._cache[i]
        if r is None:
            o = self._owner
            rid = self._ids[i]
            if rid is None:
                c = len(self._cache)
                i = xrange(c)[i] # check index and convert negative
                rid = self._ids[i] = \
                    o._backend.get_member(o._id, self._id, i)
            r = self._cache[i] = o.get_element(rid, default)
        return r

    def get_member_id(self, i):
        """Return id-ref of the element with index i.

        See also `__getitem__`  and `get_member`.
        """
        assert isinstance(i, (int, long)), "The index must be an integer"
        r = self._ids[i]
        if r is None:
            o = self._owner
            c = len(self._ids)
            i = xrange(c)[i] # check index and convert negative
            r = self._ids[i] = o._backend.get_member(o._id, self._id, i)
        return r

#
