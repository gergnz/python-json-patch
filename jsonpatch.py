# -*- coding: utf-8 -*-
#
# python-json-patch - An implementation of the JSON Patch format
# https://github.com/stefankoegl/python-json-patch
#
# Copyright (c) 2011 Stefan Kögl <stefan@skoegl.net>
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 3. The name of the author may not be used to endorse or promote products
#    derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
# OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
# NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
# THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
#

"""Apply JSON-Patches according to
http://tools.ietf.org/html/draft-pbryan-json-patch-04"""

# Will be parsed by setup.py to determine package metadata
__author__ = 'Stefan Kögl <stefan@skoegl.net>'
__version__ = '0.1'
__website__ = 'https://github.com/stefankoegl/python-json-patch'
__license__ = 'Modified BSD License'


import json


class JsonPatchException(Exception):
    """Base Json Patch exception"""


class JsonPatchConflict(JsonPatchException):
    """Raises if patch could be applied due to conflict situations such as:
    - attempt to add object key then it already exists;
    - attempt to operate with nonexistence object key;
    - attempt to insert value to array at position beyond of it size;
    - etc.
    """


def apply_patch(doc, patch):
    """Apply list of patches to specified json document.

    >>> doc = {'foo': 'bar'}
    >>> other = apply_patch(doc, [{'add': '/baz', 'value': 'qux'}])
    >>> doc is other
    True
    >>> doc
    {'foo': 'bar', 'baz': 'qux'}
    """

    patch = JsonPatch(patch)
    return patch.apply(doc)

def make_patch(src, dst):
    """Generates patch by comparing of two objects.

    >>> src = {'foo': 'bar', 'numbers': [1, 3, 4, 8]}
    >>> dst = {'baz': 'qux', 'numbers': [1, 4, 7]}
    >>> patch = make_patch(src, dst)
    >>> patch.apply(src)    #doctest: +ELLIPSIS
    {...}
    >>> src == dst
    True
    """
    def compare_values(path, value, other):
        if isinstance(value, dict) and isinstance(other, dict):
            for operation in compare_dict(path, value, other):
                yield operation
        elif isinstance(value, list) and isinstance(other, list):
            for operation in compare_list(path, value, other):
                yield operation
        else:
            yield {'replace': '/'.join(path), 'value': other}

    def compare_dict(path, src, dst):
        for key in src:
            if key not in dst:
                yield {'remove': '/'.join(path + [key])}
            elif src[key] != dst[key]:
                current = path + [key]
                for operation in compare_values(current, src[key], dst[key]):
                    yield operation
        for key in dst:
            if key not in src:
                yield {'add': '/'.join(path + [key]), 'value': dst[key]}

    def compare_list(path, src, dst):
        lsrc, ldst = len(src), len(dst)
        for idx in reversed(range(max(lsrc, ldst))):
            if idx < lsrc and idx < ldst:
                current = path + [str(idx)]
                for operation in compare_values(current, src[idx], dst[idx]):
                    yield operation
            elif idx < ldst:
                yield {'add': '/'.join(path + [str(idx)]),
                       'value': dst[idx]}
            elif idx < lsrc:
                yield {'remove': '/'.join(path + [str(idx)])}

    return JsonPatch(list(compare_dict([''], src, dst)))


class JsonPatch(object):
    """A JSON Patch is a list of Patch Operations.

    >>> patch = JsonPatch([
    ...     {'add': '/foo', 'value': 'bar'},
    ...     {'add': '/baz', 'value': [1, 2, 3]},
    ...     {'remove': '/baz/1'},
    ...     {'test': '/baz', 'value': [1, 3]},
    ...     {'replace': '/baz/0', 'value': 42},
    ...     {'remove': '/baz/1'},
    ... ])
    >>> doc = {}
    >>> patch.apply(doc)
    {'foo': 'bar', 'baz': [42]}
    """

    def __init__(self, patch):
        self.patch = patch

        self.operations = {
            'remove': RemoveOperation,
            'add': AddOperation,
            'replace': ReplaceOperation,
            'move': MoveOperation,
            'test': TestOperation
        }

    def __str__(self):
        """str(self) -> self.to_string()"""
        return self.to_string()

    @classmethod
    def from_string(cls, patch_str):
        """Creates JsonPatch instance from string source."""
        patch = json.loads(patch_str)
        return cls(patch)

    def to_string(self):
        """Returns patch set as JSON string."""
        return json.dumps(self.patch)

    def apply(self, obj):
        """Applies the patch to given object."""

        for operation in self.patch:
            operation = self._get_operation(operation)
            operation.apply(obj)

        return obj

    def _get_operation(self, operation):
        for action, op_cls in self.operations.items():
            if action in operation:
                location = operation[action]
                return op_cls(location, operation)

        raise JsonPatchException("invalid operation '%s'" % operation)


class PatchOperation(object):
    """A single operation inside a JSON Patch."""

    def __init__(self, location, operation):
        self.location = location
        self.operation = operation

    def apply(self, obj):
        """Abstract method that applies patch operation to specified object."""
        raise NotImplementedError('should implement patch operation.')

    def locate(self, obj, location, last_must_exist=True):
        """Walks through the object according to location.

        Returns the last step as (sub-object, last location-step)."""

        parts = location.split('/')
        if parts.pop(0) != '':
            raise JsonPatchException('location must starts with /')

        for part in parts[:-1]:
            obj, _ = self._step(obj, part)

        _, last_loc = self._step(obj, parts[-1], must_exist=last_must_exist)
        return obj, last_loc

    def _step(self, obj, loc_part, must_exist=True):
        """Goes one step in a locate() call."""

        if isinstance(obj, dict):
            part_variants = [loc_part]
            for variant in part_variants:
                if variant not in obj:
                    continue
                return obj[variant], variant
        elif isinstance(obj, list):
            part_variants = [int(loc_part)]
            for variant in part_variants:
                if variant >= len(obj):
                    continue
                return obj[variant], variant
        else:
            raise ValueError('list or dict expected, got %r' % type(obj))

        if must_exist:
            raise JsonPatchConflict('key %s not found' % loc_part)
        else:
            return obj, part_variants[0]


class RemoveOperation(PatchOperation):
    """Removes an object property or an array element."""

    def apply(self, obj):
        subobj, part = self.locate(obj, self.location)
        del subobj[part]


class AddOperation(PatchOperation):
    """Adds an object property or an array element."""

    def apply(self, obj):
        value = self.operation["value"]
        subobj, part = self.locate(obj, self.location, last_must_exist=False)

        if isinstance(subobj, list):
            if part > len(subobj) or part < 0:
                raise JsonPatchConflict("can't insert outside of list")

            subobj.insert(part, value)

        elif isinstance(subobj, dict):
            if part in subobj:
                raise JsonPatchConflict("object '%s' already exists" % part)

            subobj[part] = value

        else:
            raise JsonPatchConflict("can't add to type '%s'"
                                    "" % subobj.__class__.__name__)


class ReplaceOperation(PatchOperation):
    """Replaces an object property or an array element by new value."""

    def apply(self, obj):
        value = self.operation["value"]
        subobj, part = self.locate(obj, self.location)

        if isinstance(subobj, list):
            if part > len(subobj) or part < 0:
                raise JsonPatchConflict("can't replace outside of list")

        elif isinstance(subobj, dict):
            if not part in subobj:
                raise JsonPatchConflict("can't replace non-existant object '%s'"
                                        "" % part)

        else:
            raise JsonPatchConflict("can't replace in type '%s'"
                                    "" % subobj.__class__.__name__)

        subobj[part] = value


class MoveOperation(PatchOperation):
    """Moves an object property or an array element to new location."""

    def apply(self, obj):
        subobj, part = self.locate(obj, self.location)
        value = subobj[part]
        RemoveOperation(self.location, self.operation).apply(obj)
        AddOperation(self.operation['to'], {'value': value}).apply(obj)


class TestOperation(PatchOperation):
    """Test value by specified location."""

    def apply(self, obj):
        value = self.operation['value']
        subobj, part = self.locate(obj, self.location)
        assert subobj[part] == value
