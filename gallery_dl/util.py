# -*- coding: utf-8 -*-

# Copyright 2017-2019 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Utility functions and classes"""

import re
import os
import sys
import json
import time
import shutil
import string
import _string
import sqlite3
import datetime
import operator
import itertools
import urllib.parse
from email.utils import mktime_tz, parsedate_tz
from . import text, exception


def bencode(num, alphabet="0123456789"):
    """Encode an integer into a base-N encoded string"""
    data = ""
    base = len(alphabet)
    while num:
        num, remainder = divmod(num, base)
        data = alphabet[remainder] + data
    return data


def bdecode(data, alphabet="0123456789"):
    """Decode a base-N encoded string ( N = len(alphabet) )"""
    num = 0
    base = len(alphabet)
    for c in data:
        num *= base
        num += alphabet.index(c)
    return num


def advance(iterable, num):
    """"Advance the iterable by 'num' steps"""
    iterator = iter(iterable)
    next(itertools.islice(iterator, num, num), None)
    return iterator


def raises(obj):
    """Returns a function that raises 'obj' as exception"""
    def wrap():
        raise obj
    return wrap


def combine_dict(a, b):
    """Recursively combine the contents of 'b' into 'a'"""
    for key, value in b.items():
        if key in a and isinstance(value, dict) and isinstance(a[key], dict):
            combine_dict(a[key], value)
        else:
            a[key] = value
    return a


def transform_dict(a, func):
    """Recursively apply 'func' to all values in 'a'"""
    for key, value in a.items():
        if isinstance(value, dict):
            transform_dict(value, func)
        else:
            a[key] = func(value)


def number_to_string(value, numbers=(int, float)):
    """Convert numbers (int, float) to string; Return everything else as is."""
    return str(value) if value.__class__ in numbers else value


def to_string(value):
    """str() with "better" defaults"""
    if not value:
        return ""
    if value.__class__ is list:
        try:
            return ", ".join(value)
        except Exception:
            return ", ".join(map(str, value))
    return str(value)


def dump_json(obj, fp=sys.stdout, ensure_ascii=True, indent=4):
    """Serialize 'obj' as JSON and write it to 'fp'"""
    json.dump(
        obj, fp,
        ensure_ascii=ensure_ascii,
        indent=indent,
        default=str,
        sort_keys=True,
    )
    fp.write("\n")


def expand_path(path):
    """Expand environment variables and tildes (~)"""
    if not path:
        return path
    if not isinstance(path, str):
        path = os.path.join(*path)
    return os.path.expandvars(os.path.expanduser(path))


def code_to_language(code, default=None):
    """Map an ISO 639-1 language code to its actual name"""
    return CODES.get((code or "").lower(), default)


def language_to_code(lang, default=None):
    """Map a language name to its ISO 639-1 code"""
    if lang is None:
        return default
    lang = lang.capitalize()
    for code, language in CODES.items():
        if language == lang:
            return code
    return default


CODES = {
    "ar": "Arabic",
    "bg": "Bulgarian",
    "ca": "Catalan",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "jp": "Japanese",
    "ko": "Korean",
    "ms": "Malay",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "zh": "Chinese",
}

SPECIAL_EXTRACTORS = {"oauth", "recursive", "test"}


class UniversalNone():
    """None-style object that supports more operations than None itself"""
    __slots__ = ()

    def __getattribute__(self, _):
        return self

    def __getitem__(self, _):
        return self

    @staticmethod
    def __bool__():
        return False

    @staticmethod
    def __str__():
        return "None"

    __repr__ = __str__


NONE = UniversalNone()


def build_predicate(predicates):
    if not predicates:
        return lambda url, kwds: True
    elif len(predicates) == 1:
        return predicates[0]
    else:
        return ChainPredicate(predicates)


class RangePredicate():
    """Predicate; True if the current index is in the given range"""
    def __init__(self, rangespec):
        self.ranges = self.optimize_range(self.parse_range(rangespec))
        self.index = 0

        if self.ranges:
            self.lower, self.upper = self.ranges[0][0], self.ranges[-1][1]
        else:
            self.lower, self.upper = 0, 0

    def __call__(self, url, kwds):
        self.index += 1

        if self.index > self.upper:
            raise exception.StopExtraction()

        for lower, upper in self.ranges:
            if lower <= self.index <= upper:
                return True
        return False

    @staticmethod
    def parse_range(rangespec):
        """Parse an integer range string and return the resulting ranges

        Examples:
            parse_range("-2,4,6-8,10-") -> [(1,2), (4,4), (6,8), (10,INTMAX)]
            parse_range(" - 3 , 4-  4, 2-6") -> [(1,3), (4,4), (2,6)]
        """
        ranges = []

        for group in rangespec.split(","):
            if not group:
                continue
            first, sep, last = group.partition("-")
            if not sep:
                beg = end = int(first)
            else:
                beg = int(first) if first.strip() else 1
                end = int(last) if last.strip() else sys.maxsize
            ranges.append((beg, end) if beg <= end else (end, beg))

        return ranges

    @staticmethod
    def optimize_range(ranges):
        """Simplify/Combine a parsed list of ranges

        Examples:
            optimize_range([(2,4), (4,6), (5,8)]) -> [(2,8)]
            optimize_range([(1,1), (2,2), (3,6), (8,9))]) -> [(1,6), (8,9)]
        """
        if len(ranges) <= 1:
            return ranges

        ranges.sort()
        riter = iter(ranges)
        result = []

        beg, end = next(riter)
        for lower, upper in riter:
            if lower > end+1:
                result.append((beg, end))
                beg, end = lower, upper
            elif upper > end:
                end = upper
        result.append((beg, end))
        return result


class UniquePredicate():
    """Predicate; True if given URL has not been encountered before"""
    def __init__(self):
        self.urls = set()

    def __call__(self, url, kwds):
        if url.startswith("text:"):
            return True
        if url not in self.urls:
            self.urls.add(url)
            return True
        return False


class FilterPredicate():
    """Predicate; True if evaluating the given expression returns True"""
    globalsdict = {
        "parse_int": text.parse_int,
        "urlsplit": urllib.parse.urlsplit,
        "datetime": datetime.datetime,
        "abort": raises(exception.StopExtraction()),
        "re": re,
    }

    def __init__(self, filterexpr, target="image"):
        name = "<{} filter>".format(target)
        self.codeobj = compile(filterexpr, name, "eval")

    def __call__(self, url, kwds):
        try:
            return eval(self.codeobj, self.globalsdict, kwds)
        except exception.GalleryDLException:
            raise
        except Exception as exc:
            raise exception.FilterError(exc)


class ChainPredicate():
    """Predicate; True if all of its predicates return True"""
    def __init__(self, predicates):
        self.predicates = predicates

    def __call__(self, url, kwds):
        for pred in self.predicates:
            if not pred(url, kwds):
                return False
        return True


class ExtendedUrl():
    """URL with attached config key-value pairs"""
    def __init__(self, url, gconf, lconf):
        self.value, self.gconfig, self.lconfig = url, gconf, lconf

    def __str__(self):
        return self.value


class Formatter():
    """Custom, extended version of string.Formatter

    This string formatter implementation is a mostly performance-optimized
    variant of the original string.Formatter class. Unnecessary features have
    been removed (positional arguments, unused argument check) and new
    formatting options have been added.

    Extra Conversions:
    - "l": calls str.lower on the target value
    - "u": calls str.upper
    - "c": calls str.capitalize
    - "C": calls string.capwords
    - "U": calls urllib.parse.unquote
    - "S": calls util.to_string()
    - Example: {f!l} -> "example"; {f!u} -> "EXAMPLE"

    Extra Format Specifiers:
    - "?<before>/<after>/":
        Adds <before> and <after> to the actual value if it evaluates to True.
        Otherwise the whole replacement field becomes an empty string.
        Example: {f:?-+/+-/} -> "-+Example+-" (if "f" contains "Example")
                             -> ""            (if "f" is None, 0, "")

    - "L<maxlen>/<replacement>/":
        Replaces the output with <replacement> if its length (in characters)
        exceeds <maxlen>. Otherwise everything is left as is.
        Example: {f:L5/too long/} -> "foo"      (if "f" is "foo")
                                  -> "too long" (if "f" is "foobar")

    - "J<separator>/":
        Joins elements of a list (or string) using <separator>
        Example: {f:J - /} -> "a - b - c" (if "f" is ["a", "b", "c"])

    - "R<old>/<new>/":
        Replaces all occurrences of <old> with <new>
        Example: {f:R /_/} -> "f_o_o_b_a_r" (if "f" is "f o o b a r")
    """
    CONVERSIONS = {
        "l": str.lower,
        "u": str.upper,
        "c": str.capitalize,
        "C": string.capwords,
        "U": urllib.parse.unquote,
        "S": to_string,
        "s": str,
        "r": repr,
        "a": ascii,
    }

    def __init__(self, format_string, default=None):
        self.default = default
        self.result = []
        self.fields = []

        for literal_text, field_name, format_spec, conversion in \
                _string.formatter_parser(format_string):
            if literal_text:
                self.result.append(literal_text)
            if field_name:
                self.fields.append((
                    len(self.result),
                    self._field_access(field_name, format_spec, conversion),
                ))
                self.result.append("")

        if len(self.result) == 1:
            if self.fields:
                self.format_map = self.fields[0][1]
            else:
                self.format_map = lambda _: format_string
            del self.result
            del self.fields

    def format_map(self, kwargs):
        """Apply 'kwargs' to the initial format_string and return its result"""
        for index, func in self.fields:
            self.result[index] = func(kwargs)
        return "".join(self.result)

    def _field_access(self, field_name, format_spec, conversion):
        first, rest = _string.formatter_field_name_split(field_name)

        funcs = []
        for is_attr, key in rest:
            if is_attr:
                func = operator.attrgetter
            elif ":" in key:
                func = self._slicegetter
            else:
                func = operator.itemgetter
            funcs.append(func(key))

        if conversion:
            funcs.append(self.CONVERSIONS[conversion])

        if format_spec:
            if format_spec[0] == "?":
                func = self._format_optional
            elif format_spec[0] == "L":
                func = self._format_maxlen
            elif format_spec[0] == "J":
                func = self._format_join
            elif format_spec[0] == "R":
                func = self._format_replace
            else:
                func = self._format_default
            fmt = func(format_spec)
        else:
            fmt = str

        if funcs:
            return self._apply(first, funcs, fmt)
        return self._apply_simple(first, fmt)

    def _apply_simple(self, key, fmt):
        def wrap(obj):
            if key in obj:
                obj = obj[key]
            else:
                obj = self.default
            return fmt(obj)
        return wrap

    def _apply(self, key, funcs, fmt):
        def wrap(obj):
            try:
                obj = obj[key]
                for func in funcs:
                    obj = func(obj)
            except Exception:
                obj = self.default
            return fmt(obj)
        return wrap

    @staticmethod
    def _slicegetter(key):
        start, _, stop = key.partition(":")
        stop, _, step = stop.partition(":")
        start = int(start) if start else None
        stop = int(stop) if stop else None
        step = int(step) if step else None
        return operator.itemgetter(slice(start, stop, step))

    @staticmethod
    def _format_optional(format_spec):
        def wrap(obj):
            if not obj:
                return ""
            return before + format(obj, format_spec) + after
        before, after, format_spec = format_spec.split("/", 2)
        before = before[1:]
        return wrap

    @staticmethod
    def _format_maxlen(format_spec):
        def wrap(obj):
            obj = format(obj, format_spec)
            return obj if len(obj) <= maxlen else replacement
        maxlen, replacement, format_spec = format_spec.split("/", 2)
        maxlen = text.parse_int(maxlen[1:])
        return wrap

    @staticmethod
    def _format_join(format_spec):
        def wrap(obj):
            obj = separator.join(obj)
            return format(obj, format_spec)
        separator, _, format_spec = format_spec.partition("/")
        separator = separator[1:]
        return wrap

    @staticmethod
    def _format_replace(format_spec):
        def wrap(obj):
            obj = obj.replace(old, new)
            return format(obj, format_spec)
        old, new, format_spec = format_spec.split("/", 2)
        old = old[1:]
        return wrap

    @staticmethod
    def _format_default(format_spec):
        def wrap(obj):
            return format(obj, format_spec)
        return wrap


class PathFormat():

    def __init__(self, extractor):
        filename_fmt = extractor.config("filename", extractor.filename_fmt)
        directory_fmt = extractor.config("directory", extractor.directory_fmt)
        kwdefault = extractor.config("keywords-default")

        try:
            self.filename_formatter = Formatter(
                filename_fmt, kwdefault).format_map
        except Exception as exc:
            raise exception.FormatError(exc, "filename")

        try:
            self.directory_formatters = [
                Formatter(dirfmt, kwdefault).format_map
                for dirfmt in directory_fmt
            ]
        except Exception as exc:
            raise exception.FormatError(exc, "directory")

        self.directory = self.realdirectory = ""
        self.filename = ""
        self.extension = ""
        self.prefix = ""
        self.kwdict = {}
        self.delete = False
        self.path = self.realpath = self.temppath = ""

        basedir = expand_path(
            extractor.config("base-directory", (".", "gallery-dl")))
        if os.altsep and os.altsep in basedir:
            basedir = basedir.replace(os.altsep, os.sep)
        if basedir[-1] != os.sep:
            basedir += os.sep
        self.basedirectory = basedir

        restrict = extractor.config("path-restrict", "auto")
        if restrict == "auto":
            restrict = "\\\\|/<>:\"?*" if os.name == "nt" else "/"
        elif restrict == "unix":
            restrict = "/"
        elif restrict == "windows":
            restrict = "\\\\|/<>:\"?*"

        remove = extractor.config("path-remove", "\x00-\x1f\x7f")

        self.clean_segment = self._build_cleanfunc(restrict, "_")
        self.clean_path = self._build_cleanfunc(remove, "")

    @staticmethod
    def _build_cleanfunc(chars, repl):
        if not chars:
            return lambda x: x
        elif len(chars) == 1:
            def func(x, c=chars, r=repl):
                return x.replace(c, r)
        else:
            def func(x, sub=re.compile("[" + chars + "]").sub, r=repl):
                return sub(r, x)
        return func

    def open(self, mode="wb"):
        """Open file and return a corresponding file object"""
        return open(self.temppath, mode)

    def exists(self, archive=None):
        """Return True if the file exists on disk or in 'archive'"""
        if archive and self.kwdict in archive:
            return self.fix_extension()
        if self.extension and os.path.exists(self.realpath):
            return self.check_file()
        return False

    @staticmethod
    def check_file():
        return True

    def _enum_file(self):
        num = 1
        while True:
            self.prefix = str(num) + "."
            self.set_extension(self.extension, False)
            if not os.path.exists(self.realpath):
                return False
            num += 1

    def set_directory(self, kwdict):
        """Build directory path and create it if necessary"""

        # Build path segments by applying 'kwdict' to directory format strings
        segments = []
        append = segments.append
        try:
            for formatter in self.directory_formatters:
                segment = formatter(kwdict).strip()
                if segment:
                    append(self.clean_segment(segment))
        except Exception as exc:
            raise exception.FormatError(exc, "directory")

        # Join path segements
        sep = os.sep
        directory = self.clean_path(self.basedirectory + sep.join(segments))

        # Ensure 'directory' ends with a path separator
        if segments:
            directory += sep
        self.directory = directory

        if os.name == "nt":
            # Enable longer-than-260-character paths on Windows
            directory = "\\\\?\\" + os.path.abspath(directory)

            # abspath() in Python 3.7+ removes trailing path separators (#402)
            if directory[-1] != sep:
                directory += sep

        self.realdirectory = directory

        # Create directory tree
        os.makedirs(self.realdirectory, exist_ok=True)

    def set_filename(self, kwdict):
        """Set general filename data"""
        self.kwdict = kwdict
        self.temppath = self.prefix = ""
        self.extension = kwdict["extension"]

        if self.extension:
            self.build_path()

    def set_extension(self, extension, real=True):
        """Set filename extension"""
        if real:
            self.extension = extension
        self.kwdict["extension"] = self.prefix + extension
        self.build_path()

    def fix_extension(self, _=None):
        """Fix filenames without a given filename extension"""
        if not self.extension:
            self.set_extension("", False)
            if self.path[-1] == ".":
                self.path = self.path[:-1]
                self.temppath = self.realpath = self.realpath[:-1]
        return True

    def build_path(self):
        """Use filename metadata and directory to build a full path"""

        # Apply 'kwdict' to filename format string
        try:
            self.filename = filename = self.clean_path(self.clean_segment(
                self.filename_formatter(self.kwdict)))
        except Exception as exc:
            raise exception.FormatError(exc, "filename")

        # Combine directory and filename to full paths
        self.path = self.directory + filename
        self.realpath = self.realdirectory + filename
        if not self.temppath:
            self.temppath = self.realpath

    def part_enable(self, part_directory=None):
        """Enable .part file usage"""
        if self.extension:
            self.temppath += ".part"
        else:
            self.set_extension("part", False)
        if part_directory:
            self.temppath = os.path.join(
                part_directory,
                os.path.basename(self.temppath),
            )

    def part_size(self):
        """Return size of .part file"""
        try:
            return os.stat(self.temppath).st_size
        except OSError:
            pass
        return 0

    def finalize(self):
        """Move tempfile to its target location"""
        if self.delete:
            self.delete = False
            os.unlink(self.temppath)
            return

        if self.temppath != self.realpath:
            # Move temp file to its actual location
            try:
                os.replace(self.temppath, self.realpath)
            except OSError:
                shutil.copyfile(self.temppath, self.realpath)
                os.unlink(self.temppath)

        if "_mtime" in self.kwdict:
            # Set file modification time
            mtime = self.kwdict["_mtime"]
            if mtime:
                try:
                    if isinstance(mtime, str):
                        mtime = mktime_tz(parsedate_tz(mtime))
                    os.utime(self.realpath, (time.time(), mtime))
                except Exception:
                    pass


class DownloadArchive():

    def __init__(self, path, extractor):
        con = sqlite3.connect(path)
        con.isolation_level = None
        self.close = con.close
        self.cursor = con.cursor()
        self.cursor.execute("CREATE TABLE IF NOT EXISTS archive "
                            "(entry PRIMARY KEY) WITHOUT ROWID")
        self.keygen = (extractor.category + extractor.config(
            "archive-format", extractor.archive_fmt)
        ).format_map

    def __contains__(self, kwdict):
        """Return True if the item described by 'kwdict' exists in archive"""
        key = self.keygen(kwdict)
        self.cursor.execute(
            "SELECT 1 FROM archive WHERE entry=? LIMIT 1", (key,))
        return self.cursor.fetchone()

    def add(self, kwdict):
        """Add item described by 'kwdict' to archive"""
        key = self.keygen(kwdict)
        self.cursor.execute(
            "INSERT OR IGNORE INTO archive VALUES (?)", (key,))
