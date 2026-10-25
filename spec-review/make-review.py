#!/usr/bin/env python3
"""Generate a self-contained spec-to-code review page.

Validates a mapping.json + changes.diff pair and injects both into a copy of
template.html. See README.md for the input formats.
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

PLACEHOLDERS = ("/*MAPPING_JSON*/", "/*CHANGES_DIFF*/", "/*META_JSON*/")
DEFAULT_TITLE = "Spec review"

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


class InputError(Exception):
    """A fatal problem with the inputs; the message is printed after 'error:'."""


# --------------------------------------------------------------------------
# Diff parsing (only as much as validation needs: paths, lines, hunk shape)
# --------------------------------------------------------------------------

_ESCAPES = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r",
            "t": "\t", "v": "\v", '"': '"', "\\": "\\"}


def unquote_path(raw):
    """Undo git's C-style quoting for simple cases ("a/x y" or octal bytes)."""
    raw = raw.strip()
    if not (len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"'):
        return raw
    body, out, i = raw[1:-1], bytearray(), 0
    while i < len(body):
        c = body[i]
        if c == "\\" and i + 1 < len(body):
            n = body[i + 1]
            if n in "01234567" and re.match(r"[0-7]{3}", body[i + 1:i + 4]):
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
                continue
            out.extend(_ESCAPES.get(n, n).encode("utf-8"))
            i += 2
            continue
        out.extend(c.encode("utf-8"))
        i += 1
    return out.decode("utf-8", errors="replace")


def strip_prefix(path, prefix):
    if path == "/dev/null":
        return None
    return path[len(prefix):] if path.startswith(prefix) else path


def split_git_header(rest):
    """Split the 'a/X b/Y' part of a 'diff --git' line into (X, Y)."""
    rest = rest.strip()
    if rest.startswith('"'):
        m = re.match(r'^("(?:[^"\\]|\\.)*")\s+(.*)$', rest)
        if m:
            return strip_prefix(unquote_path(m.group(1)), "a/"), \
                strip_prefix(unquote_path(m.group(2)), "b/")
    if rest.endswith('"'):
        m = re.match(r'^(.*?)\s+("(?:[^"\\]|\\.)*")$', rest)
        if m:
            return strip_prefix(m.group(1), "a/"), strip_prefix(unquote_path(m.group(2)), "b/")
    # Unquoted: assume both sides are equal when ambiguous ("a/x y b/x y").
    half = (len(rest) - 1) // 2
    if len(rest) % 2 == 1 and rest[half] == " " and rest[:half][2:] == rest[half + 1:][2:]:
        return strip_prefix(rest[:half], "a/"), strip_prefix(rest[half + 1:], "b/")
    idx = rest.find(" b/")
    if idx > 0:
        return strip_prefix(rest[:idx], "a/"), strip_prefix(rest[idx + 1:], "b/")
    return rest, rest


def parse_diff(text):
    """Parse a unified git diff into a list of file dicts.

    Each file: old_path, new_path, path, new, deleted, renamed, binary,
    hunks (list of (old_start, old_count, new_start, new_count)),
    lines (hunk headers and code lines, without their +/-/space marker) and
    sides ({"old": {line_no: text}, "new": {line_no: text}}).
    """
    files = []
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].rstrip("\r")
        if not line.startswith("diff --git "):
            i += 1
            continue
        old_path, new_path = split_git_header(line[len("diff --git "):])
        f = {"old_path": old_path, "new_path": new_path, "new": False, "deleted": False,
             "renamed": False, "binary": False, "hunks": [], "lines": [],
             "sides": {"old": {}, "new": {}}}
        files.append(f)
        i += 1
        while i < n:
            line = lines[i].rstrip("\r")
            if line.startswith("diff --git "):
                break
            m = HUNK_RE.match(line)
            if m:
                old_start, new_start = int(m.group(1)), int(m.group(3))
                old_count = 1 if m.group(2) is None else int(m.group(2))
                new_count = 1 if m.group(4) is None else int(m.group(4))
                f["hunks"].append((old_start, old_count, new_start, new_count))
                f["lines"].append(m.group(5))
                old_left, new_left = old_count, new_count
                old_no, new_no = old_start, new_start
                i += 1
                while i < n and (old_left > 0 or new_left > 0):
                    row = lines[i]
                    tag = row[:1]
                    if tag == "\\":
                        pass
                    elif tag == "+":
                        f["sides"]["new"][new_no] = row[1:]
                        new_left -= 1
                        new_no += 1
                    elif tag == "-":
                        f["sides"]["old"][old_no] = row[1:]
                        old_left -= 1
                        old_no += 1
                    elif tag == " " or row == "":
                        f["sides"]["old"][old_no] = f["sides"]["new"][new_no] = row[1:]
                        old_left -= 1
                        new_left -= 1
                        old_no += 1
                        new_no += 1
                    else:
                        break
                    if tag != "\\":
                        f["lines"].append(row[1:])
                    i += 1
                # A trailing "\ No newline" after the last counted row.
                while i < n and lines[i].startswith("\\"):
                    i += 1
                continue
            if line.startswith("new file mode"):
                f["new"] = True
            elif line.startswith("deleted file mode"):
                f["deleted"] = True
            elif line.startswith("rename from "):
                f["old_path"] = unquote_path(line[len("rename from "):])
                f["renamed"] = True
            elif line.startswith("rename to "):
                f["new_path"] = unquote_path(line[len("rename to "):])
                f["renamed"] = True
            elif line.startswith("--- "):
                p = strip_prefix(unquote_path(line[4:].split("\t")[0]), "a/")
                if p is None:
                    f["new"] = True
                else:
                    f["old_path"] = p
            elif line.startswith("+++ "):
                p = strip_prefix(unquote_path(line[4:].split("\t")[0]), "b/")
                if p is None:
                    f["deleted"] = True
                else:
                    f["new_path"] = p
            elif line.startswith("Binary files ") or line == "GIT binary patch":
                f["binary"] = True
            i += 1
    for f in files:
        f["path"] = f["old_path"] if f["deleted"] else f["new_path"]
    return files


def is_complete(f):
    """New/deleted/binary files, or exactly one hunk starting at line 1 on both sides."""
    if f["new"] or f["deleted"] or f["binary"] or not f["hunks"]:
        return True
    if len(f["hunks"]) != 1:
        return False
    old_start, old_count, new_start, new_count = f["hunks"][0]
    return (old_start == (0 if old_count == 0 else 1)
            and new_start == (0 if new_count == 0 else 1))


def symbol_pattern(symbol):
    return re.compile(r"(?<![\w$])" + re.escape(symbol) + r"(?![\w$])", re.ASCII)


LINES_RE = re.compile(r"^(old|new):(\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*)$")


def parse_lines(value):
    """Parse 'new:10-20,40' into ('new', [(10, 20), (40, 40)]).

    Raises ValueError with a short reason when the value is malformed.
    """
    if not isinstance(value, str):
        raise ValueError("must be a string like \"new:10-20\"")
    m = LINES_RE.match(value.replace(" ", ""))
    if not m:
        raise ValueError("must look like \"new:10-20\" or \"old:5-8,12\", got %s" % json.dumps(value))
    ranges = []
    for part in m.group(2).split(","):
        lo, _, hi = part.partition("-")
        lo, hi = int(lo), int(hi or lo)
        if lo < 1 or hi < lo:
            raise ValueError("invalid range %s in %s" % (part, json.dumps(value)))
        ranges.append((lo, hi))
    return m.group(1), ranges


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

def read_text(path, what):
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return fh.read()
    except FileNotFoundError:
        raise InputError("%s not found: %s" % (what, path))
    except UnicodeDecodeError as e:
        raise InputError("%s is not valid UTF-8: %s (%s)" % (what, path, e))
    except OSError as e:
        raise InputError("cannot read %s %s: %s" % (what, path, e.strerror or e))


def load_mapping(text, name):
    if text.startswith("﻿"):
        text = text[1:]
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise InputError("%s: invalid JSON at line %d, column %d: %s"
                         % (name, e.lineno, e.colno, e.msg))


def _is_nonempty_str(value):
    return isinstance(value, str) and value != ""


def validate_mapping(m):
    """Return a list of error messages (empty when the mapping is valid)."""
    errors = []
    if not isinstance(m, dict):
        return ["mapping must be a JSON object"]
    version = m.get("version")
    if "version" not in m:
        errors.append('missing "version" (must be 2)')
    elif isinstance(version, bool) or version != 2:
        errors.append("version: must be 2, got %s" % json.dumps(version))
    if "title" in m and not isinstance(m["title"], str):
        errors.append("title: must be a string")
    if "elements" not in m:
        errors.append('missing "elements"')
        return errors
    elements = m["elements"]
    if not isinstance(elements, list):
        errors.append("elements: must be an array")
        return errors
    if not elements:
        errors.append("elements: must not be empty")
        return errors

    seen = {}
    for i, el in enumerate(elements):
        loc = "elements[%d]" % i
        if not isinstance(el, dict):
            errors.append("%s: must be an object" % loc)
            continue
        for key in ("id", "text", "tests", "implementation"):
            if key not in el:
                errors.append('%s: missing "%s"' % (loc, key))
        if "id" in el:
            if not _is_nonempty_str(el["id"]):
                errors.append('%s: "id" must be a non-empty string' % loc)
            elif el["id"] in seen:
                errors.append('%s: duplicate id "%s" (first used by elements[%d])'
                              % (loc, el["id"], seen[el["id"]]))
            else:
                seen[el["id"]] = i
        if "text" in el and not _is_nonempty_str(el["text"]):
            errors.append('%s: "text" must be a non-empty string' % loc)
        for kind in ("tests", "implementation"):
            if kind not in el:
                continue
            refs = el[kind]
            if not isinstance(refs, list):
                errors.append('%s: "%s" must be an array' % (loc, kind))
                continue
            for j, ref in enumerate(refs):
                rloc = "%s.%s[%d]" % (loc, kind, j)
                if not isinstance(ref, dict):
                    errors.append("%s: must be an object" % rloc)
                    continue
                for key in ("file", "symbol"):
                    if key not in ref:
                        errors.append('%s: missing "%s"' % (rloc, key))
                    elif not _is_nonempty_str(ref[key]):
                        errors.append('%s: "%s" must be a non-empty string' % (rloc, key))
                if "lines" in ref:
                    try:
                        parse_lines(ref["lines"])
                    except ValueError as e:
                        errors.append('%s: "lines" %s' % (rloc, e))
    return errors


def check_diff_hash(mapping, diff_bytes, diff_name):
    """Error message when mapping.diffSha256 is present and doesn't match, else None."""
    if "diffSha256" not in mapping:
        return None
    expected = mapping["diffSha256"]
    if not (isinstance(expected, str) and re.match(r"^[0-9a-fA-F]{64}$", expected)):
        return "diffSha256: must be a 64-character hex SHA-256"
    actual = hashlib.sha256(diff_bytes).hexdigest()
    if expected.lower() != actual:
        return ("diffSha256 does not match %s (mapping was written for another diff; "
                "expected %s, got %s)" % (diff_name, expected.lower(), actual))
    return None


def format_lines(side, ranges):
    return "%s:%s" % (side, ",".join(str(a) if a == b else "%d-%d" % (a, b) for a, b in ranges))


def collect_warnings(mapping, files):
    """Non-fatal problems, in a stable order (elements first, then the diff)."""
    warnings = []
    by_path = {}
    for f in files:
        by_path.setdefault(f["path"], f)
    for i, el in enumerate(mapping["elements"]):
        for kind in ("tests", "implementation"):
            for j, ref in enumerate(el[kind]):
                loc = "elements[%d] (%s) %s[%d]" % (i, el["id"], kind, j)
                f = by_path.get(ref["file"])
                if f is None:
                    warnings.append("%s: file %s not in diff" % (loc, ref["file"]))
                    continue
                pattern = symbol_pattern(ref["symbol"])
                if "lines" in ref:
                    side, ranges = parse_lines(ref["lines"])
                    numbered = f["sides"][side]
                    wanted = [no for lo, hi in ranges for no in range(lo, hi + 1)]
                    label = format_lines(side, ranges)
                    if not all(no in numbered for no in wanted):
                        warnings.append("%s: lines %s not in the diff of %s"
                                        % (loc, label, ref["file"]))
                    elif not any(pattern.search(numbered[no]) for no in wanted):
                        warnings.append('%s: symbol "%s" not found in lines %s of %s'
                                        % (loc, ref["symbol"], label, ref["file"]))
                    continue
                if not any(pattern.search(line) for line in f["lines"]):
                    warnings.append('%s: symbol "%s" not found in %s'
                                    % (loc, ref["symbol"], ref["file"]))
    partial = [f["path"] for f in files if not is_complete(f)]
    if partial:
        warnings.append("diff has limited context for %d file(s) (e.g. %s); "
                        "use -U99999 for expandable files" % (len(partial), partial[0]))
    if not any(el["tests"] or el["implementation"] for el in mapping["elements"]):
        warnings.append("no linked elements")
    return warnings


# --------------------------------------------------------------------------
# Injection
# --------------------------------------------------------------------------

def to_script_json(value):
    """JSON that is safe inside a <script> element."""
    s = json.dumps(value, ensure_ascii=False)
    return s.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def inject(template, values):
    """Replace each placeholder (which must occur exactly once) in one pass."""
    spots = []
    for ph in PLACEHOLDERS:
        count = template.count(ph)
        if count != 1:
            raise InputError("template must contain placeholder %s exactly once (found %d)"
                             % (ph, count))
        spots.append((template.index(ph), ph))
    out, pos = [], 0
    for start, ph in sorted(spots):
        out.append(template[pos:start])
        out.append(values[ph])
        pos = start + len(ph)
    out.append(template[pos:])
    return "".join(out)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def build(mapping_path, diff_path, template_path):
    """Return (html, mapping, warnings) or raise InputError."""
    mapping_text = read_text(mapping_path, "mapping file")
    diff_text = read_text(diff_path, "diff file")
    template = read_text(template_path, "template")
    if not any(ph in template for ph in PLACEHOLDERS):
        raise InputError("template has no placeholders: %s" % template_path)

    mapping = load_mapping(mapping_text, os.path.basename(mapping_path))
    errors = validate_mapping(mapping)
    if isinstance(mapping, dict):
        # The diff was decoded from UTF-8 without newline translation, so this is its exact bytes.
        hash_error = check_diff_hash(mapping, diff_text.encode("utf-8"), os.path.basename(diff_path))
        if hash_error:
            errors.append(hash_error)
    files = parse_diff(diff_text)
    if not files:
        errors.append("%s: no 'diff --git' file sections found" % os.path.basename(diff_path))
    if errors:
        raise InputError("\n".join(errors))

    warnings = collect_warnings(mapping, files)
    meta = {
        "generatedAt": datetime.datetime.now(datetime.timezone.utc).astimezone()
        .isoformat(timespec="seconds"),
        "mappingFile": os.path.basename(mapping_path),
        "diffFile": os.path.basename(diff_path),
    }
    html = inject(template, {
        "/*MAPPING_JSON*/": to_script_json(mapping),
        "/*CHANGES_DIFF*/": to_script_json(diff_text),
        "/*META_JSON*/": to_script_json(meta),
    })
    return html, mapping, warnings


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="make-review.py",
        description="Build a self-contained spec-to-code review page.")
    parser.add_argument("mapping", metavar="MAPPING", help="path to mapping.json")
    parser.add_argument("diff", metavar="DIFF", help="path to changes.diff")
    parser.add_argument("-o", "--output", help="output HTML path "
                        "(default: review.html in MAPPING's directory)")
    parser.add_argument("--template", help="template path "
                        "(default: template.html next to the script)")
    args = parser.parse_args(argv)

    template_path = args.template or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "template.html")
    output = args.output or os.path.join(
        os.path.dirname(os.path.abspath(args.mapping)), "review.html")

    try:
        html, mapping, warnings = build(args.mapping, args.diff, template_path)
    except InputError as e:
        for msg in str(e).split("\n"):
            print("error: " + msg, file=sys.stderr)
        return 1

    for w in warnings:
        print("warning: " + w, file=sys.stderr)
    try:
        with open(output, "w", encoding="utf-8", newline="") as fh:
            fh.write(html)
    except OSError as e:
        print("error: cannot write %s: %s" % (output, e.strerror or e), file=sys.stderr)
        return 1

    elements = mapping["elements"]
    linked = sum(1 for el in elements if el["tests"] or el["implementation"])
    print("Wrote %s (%d elements, %d linked, %d warnings)"
          % (output, len(elements), linked, len(warnings)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
