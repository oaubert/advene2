"""
I define the class of resources.
"""

from libadvene.model.core.element import PackageElement, RESOURCE
from libadvene.model.core.content import WithContentMixin

class Resource(PackageElement, WithContentMixin):

    ADVENE_TYPE = RESOURCE

    @classmethod
    def instantiate(cls, owner, id, mimetype, model, url, *args):
        r = super(Resource, cls) \
                .instantiate(owner, id, mimetype, model, url, *args)
        r._instantiate_content(mimetype, model, url)
        return r

    @classmethod
    def create_new(cls, owner, id, mimetype, model, url):
        model_id = PackageElement._check_reference(owner, model, RESOURCE)
        cls._check_content_cls(mimetype, model_id, url, owner)
        owner._backend.create_resource(owner._id, id, mimetype, model_id, url)
        r = cls.instantiate(owner, id, mimetype, model_id, url)
        return r

    def validate_content(self, element):
        """
        Return True if element.content_data satisfies this content model.

        If this resource can not be interpreted as a content model, False
        will be returned.
        """
        # TODO implement this
        return False

#
