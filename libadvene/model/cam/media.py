from libadvene.model.cam.consts import CAM_NS_PREFIX
from libadvene.model.cam.element import CamElementMixin
from libadvene.model.consts import DC_NS_PREFIX
from libadvene.model.core.media import Media as CoreMedia

class Media(CoreMedia, CamElementMixin):
    pass

Media.make_metadata_property(DC_NS_PREFIX + "extent", "duration", default=0)
Media.make_metadata_property(CAM_NS_PREFIX + "uri", default=None)
