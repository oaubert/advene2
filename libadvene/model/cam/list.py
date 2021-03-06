from libadvene.model.cam.consts import CAMSYS_TYPE
from libadvene.model.cam.element import CamElementMixin
from libadvene.model.cam.group import CamGroupMixin
import libadvene.model.cam.util.bookkeeping as bk
from libadvene.model.core.list import List as CoreList

class List(CoreList, CamGroupMixin, CamElementMixin) :

    @classmethod
    def instantiate(cls, owner, id, *args):
        r = super(List, cls).instantiate(owner, id, *args)
        r._transtype()
        r._self_connect("modified-items", bk.update_element)
        return r

    def __iter__(self):
        # necessary to override CamGroupMixin __iter__
        return CoreList.__iter__(self)

    def _set_camsys_type(self, value, val_is_idref=False):
        super(List, self)._set_camsys_type(value, val_is_idref)
        self._transtype(value)

    def _transtype(self, systype=None):
        """
        Transtypes this List to Schema if its systype is 'schema'.

        If systype is omitted, it is retrieved from the metadata.
        """
        if systype is None:
            systype = self.get_meta(CAMSYS_TYPE, None)
        if systype == "schema":
            newtype = Schema
        else:
            newtype = List
        if self.__class__ is not newtype:
            self.__class__ = newtype

List.make_metadata_property(CAMSYS_TYPE, "system_type", default=None)

class Schema(List):
    """
    The class of annotation types.
    """
    # This class is automatically transtyped from List (and back) when 
    # CAMSYS_TYPE is modified. See List.set_meta
    pass
