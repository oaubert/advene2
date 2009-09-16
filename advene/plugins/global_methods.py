#
# Advene: Annotate Digital Videos, Exchange on the NEt
# Copyright (C) 2008 Olivier Aubert <olivier.aubert@liris.cnrs.fr>
#
# Advene is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# Advene is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Advene; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
#
""" This module contains all the global methods to be automatically added to a new
AdveneContext.
Note that those method must import every module they need _inside_ their body in
order to prevent cyclic references.

If called on an invalid target, the method should return None.
"""

name="TALES global methods"

from libadvene.model.tales import register_global_method
import sys
import inspect

def register(controller=None):
    for (name, method) in inspect.getmembers(sys.modules.get(__name__)):
        if name.startswith('_') or name.startswith('register'):
            continue
        if inspect.isfunction(method):
            register_global_method(method, name)

def formatted (target, context):
    # FIXME
    """Return a formatted timestamp as hh:mm:ss.mmmm

    This method applies to either integers (in this case, it directly
    returns the formated string), or to fragments. It returns a
    dictionary with begin, end and duration keys.
    """
    import time
    from libadvene.model.core.annotation import Annotation

    if isinstance(target, int) or isinstance(target, long):
        return u"%s.%03d" % (time.strftime("%H:%M:%S", time.gmtime(target / 1000)),
                             target % 1000)

    if isinstance(target, Annotation):
        res = {
            'begin': u'--:--:--.---',
            'end'  : u'--:--:--.---',
            'duration': u'--:--:--.---'
            }
        for k in res.keys():
            t=getattr(target, k)
            res[k] = u"%s.%03d" % (time.strftime("%H:%M:%S", time.gmtime(t / 1000)), t % 1000)
        return res
    # Fallback: invoke get_title
    c=context.globals['options']['controller']
    return c.get_title(target)

def first (target, context):
    """Return the first item of target.

    Return the first element of =target=, which must obviously be a list-like
    object.
    # FIXME: handle generators
    """
    if callable(target):
        t=target()
    else:
        t=target
    try:
        return t[0]
    except (IndexError, TypeError):
        return None

def last (target, context):
    """Return the last item of target.

    Return the last element of =target=, which must obviously be a list-like
    object.
    """
    if callable(target):
        t=target()
    else:
        t=target
    try:
        return t[-1]
    except (IndexError, TypeError):
        return None

def rest (target, context):
    """Return all but the first items of target.

    Return all elements of target but the first. =target= must obvioulsly be a
    list-like, sliceable object.
    # FIXME: handle generators
    """
    if callable(target):
        t=target()
    else:
        t=target
    try:
        return t[1:]
    except TypeError:
        return None

def sorted (target, context):
    """Return a sorted list

    This method applies either to list of annotations, that will be
    sorted according to their positions, or to any list of comparable
    items.
    """
    if (hasattr(target, '__getslice__') and len(target) > 0 and hasattr(target[0], '__cmp__')):
        l=list(target[:])
        return sorted(l)
    elif (hasattr(target, '__getslice__') and len(target) > 0 and hasattr(target[0], 'title')):
        l=list(target[:])
        return sorted(l, key=lambda e: e.title)
    else:
        return target

def length(target, context):
    """Return the length of the target.
    """
    try:
        return len(target)
    except TypeError:
        return 0
