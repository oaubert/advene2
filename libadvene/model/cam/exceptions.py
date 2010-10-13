"""
I define exceptions used in the Cinelab Application Model.
"""

from warnings import filterwarnings

class UnsafeUseWarning(Warning):
    """
    Issued whenever a method inherited from the core model is used in an
    unsafe way w.r.t. the Cinelab Application Model. This means that the CAM
    prescribes a specific way to use the method, and provides secialized
    method complying with those prescriptions.

    E.g. a_package.iter_tags is unsafe, as it will mix user tags with
    annotation types and relations types. a_package.iter_user_tags should be
    used instead.
    """
    pass

# this class should never be raised from within libadvene.model.core,
# since it is not aware of CAM distinctions
filterwarnings("ignore", category=UnsafeUseWarning,
               module="libadvene.model.core")

class LikelyMistake(Warning):
    """
    Issued whenever a method is likely mistaken for another one.

    E.g. an_annotation_type.schemas is probably meant to be
    an_annotation_type.my_schemas.
    """
    pass

class SemanticError(Exception):
    """
    Raised whenever a CAM specific metadata is used in an inconsistent way.
    """
    pass
