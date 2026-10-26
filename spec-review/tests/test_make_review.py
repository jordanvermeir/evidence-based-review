"""Tests for make-review.py (stdlib unittest only).

Run from the spec-review directory:  python3 -m unittest discover tests
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(ROOT, "make-review.py")
TEMPLATE = os.path.join(ROOT, "template.html")
EXAMPLES = os.path.join(ROOT, "examples")

_spec = importlib.util.spec_from_file_location("make_review", SCRIPT)
make_review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_review)

DIFF = """\
diff --git a/src/Foo.java b/src/Foo.java
index 1111111..2222222 100644
--- a/src/Foo.java
+++ b/src/Foo.java
@@ -1,5 +1,6 @@
 class Foo {
     void register(String email) {
-        save(email);
+        String s = "</script><b>x</b> & more";
+        save(email, s);
     }
 }
"""

PARTIAL_DIFF = """\
diff --git a/src/Foo.java b/src/Foo.java
index 1111111..2222222 100644
--- a/src/Foo.java
+++ b/src/Foo.java
@@ -10,3 +10,3 @@ class Foo {
     void register(String email) {
-        save(email);
+        store(email);
     }
"""


def element(id_, text, tests=(), impl=()):
    return {"id": id_, "text": text, "tests": list(tests), "implementation": list(impl)}


def ref(file, symbol):
    return {"file": file, "symbol": symbol}


def valid_mapping():
    return {
        "version": 2,
        "title": "Foo spec",
        "elements": [
            element("E1", "# Foo\n\n"),
            element("E2", "- Register must save.\n", [ref("src/Foo.java", "register")],
                    [ref("src/Foo.java", "Foo")]),
        ],
    }


def extract_block(html, block_id):
    m = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % block_id,
                  html, re.S)
    assert m, "block %s not found" % block_id
    return json.loads(m.group(1))


class GeneratorTestCase(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def write(self, name, content):
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(content if isinstance(content, str) else json.dumps(content, indent=2))
        return path

    def run_tool(self, *args):
        proc = subprocess.run([sys.executable, SCRIPT] + list(args),
                              capture_output=True, text=True, encoding="utf-8")
        return proc.returncode, proc.stdout, proc.stderr

    def generate(self, mapping=None, diff=DIFF, extra=()):
        m = self.write("mapping.json", valid_mapping() if mapping is None else mapping)
        d = self.write("changes.diff", diff)
        return self.run_tool(m, d, *extra)

    @property
    def default_out(self):
        return os.path.join(self.dir, "review.html")


class ErrorTests(GeneratorTestCase):
    """Every fatal error exits 1, prints a located 'error:' and writes nothing."""

    def assertFails(self, result, expected):
        code, out, err = result
        self.assertEqual(code, 1, err)
        self.assertIn("error: " + expected, err)
        self.assertEqual(out, "")
        self.assertFalse(os.path.exists(self.default_out), "output must not be written")

    def assertMappingFails(self, mapping, expected):
        self.assertFails(self.generate(mapping), expected)

    def test_missing_mapping_file(self):
        d = self.write("changes.diff", DIFF)
        self.assertFails(self.run_tool(os.path.join(self.dir, "nope.json"), d), "mapping file not found")

    def test_missing_diff_file(self):
        m = self.write("mapping.json", valid_mapping())
        self.assertFails(self.run_tool(m, os.path.join(self.dir, "nope.diff")), "diff file not found")

    def test_unreadable_input(self):
        d = self.write("changes.diff", DIFF)
        self.assertFails(self.run_tool(self.dir, d), "cannot read mapping file")

    def test_invalid_utf8(self):
        m = self.write("mapping.json", valid_mapping())
        d = os.path.join(self.dir, "changes.diff")
        with open(d, "wb") as fh:
            fh.write(b"diff --git a/x b/x\n\xff\xfe\n")
        self.assertFails(self.run_tool(m, d), "diff file is not valid UTF-8")

    def test_missing_template(self):
        self.assertFails(self.generate(extra=("--template", os.path.join(self.dir, "none.html"))),
                         "template not found")

    def test_template_without_placeholders(self):
        t = self.write("t.html", "<html><body>nothing here</body></html>")
        self.assertFails(self.generate(extra=("--template", t)), "template has no placeholders")

    def test_template_with_some_placeholders_missing(self):
        t = self.write("t.html", "<script>/*MAPPING_JSON*/</script>")
        self.assertFails(self.generate(extra=("--template", t)),
                         "template must contain placeholder /*CHANGES_DIFF*/ exactly once")

    def test_invalid_json_reports_line_and_column(self):
        self.assertMappingFails('{\n  "version": 2,\n  "elements": [,]\n}',
                                "mapping.json: invalid JSON at line 3, column 16")

    def test_mapping_not_an_object(self):
        self.assertMappingFails([1, 2], "mapping must be a JSON object")

    def test_wrong_version(self):
        m = valid_mapping()
        m["version"] = 1
        self.assertMappingFails(m, "version: must be 2, got 1")

    def test_missing_version(self):
        m = valid_mapping()
        del m["version"]
        self.assertMappingFails(m, 'missing "version"')

    def test_title_wrong_type(self):
        m = valid_mapping()
        m["title"] = 5
        self.assertMappingFails(m, "title: must be a string")

    def test_elements_missing(self):
        self.assertMappingFails({"version": 2}, 'missing "elements"')

    def test_elements_empty(self):
        self.assertMappingFails({"version": 2, "elements": []}, "elements: must not be empty")

    def test_elements_not_array(self):
        self.assertMappingFails({"version": 2, "elements": {}}, "elements: must be an array")

    def test_element_not_object(self):
        m = valid_mapping()
        m["elements"].append("E3")
        self.assertMappingFails(m, "elements[2]: must be an object")

    def test_element_missing_fields(self):
        for key in ("id", "text", "tests", "implementation"):
            with self.subTest(key=key):
                m = valid_mapping()
                del m["elements"][1][key]
                self.assertMappingFails(m, 'elements[1]: missing "%s"' % key)

    def test_element_wrong_types(self):
        cases = [("id", 7, '"id" must be a non-empty string'),
                 ("id", "", '"id" must be a non-empty string'),
                 ("text", None, '"text" must be a non-empty string'),
                 ("text", "", '"text" must be a non-empty string'),
                 ("tests", {}, '"tests" must be an array'),
                 ("implementation", "x", '"implementation" must be an array')]
        for key, value, msg in cases:
            with self.subTest(key=key, value=value):
                m = valid_mapping()
                m["elements"][1][key] = value
                self.assertMappingFails(m, "elements[1]: " + msg)

    def test_duplicate_id(self):
        m = valid_mapping()
        m["elements"].append(element("E1", "more\n"))
        self.assertMappingFails(m, 'elements[2]: duplicate id "E1" (first used by elements[0])')

    def test_reference_not_object(self):
        m = valid_mapping()
        m["elements"][1]["tests"] = ["src/Foo.java"]
        self.assertMappingFails(m, "elements[1].tests[0]: must be an object")

    def test_reference_missing_or_empty_fields(self):
        cases = [({"symbol": "x"}, 'missing "file"'),
                 ({"file": "src/Foo.java"}, 'missing "symbol"'),
                 ({"file": "", "symbol": "x"}, '"file" must be a non-empty string'),
                 ({"file": "src/Foo.java", "symbol": ""}, '"symbol" must be a non-empty string')]
        for r, msg in cases:
            with self.subTest(ref=r):
                m = valid_mapping()
                m["elements"][1]["implementation"] = [ref("src/Foo.java", "Foo"), r]
                self.assertMappingFails(m, "elements[1].implementation[1]: " + msg)

    def test_malformed_lines(self):
        cases = [(42, 'must be a string like "new:10-20"'),
                 ("10-20", 'must look like "new:10-20" or "old:5-8,12", got "10-20"'),
                 ("both:1-2", 'must look like'),
                 ("new:", 'must look like'),
                 ("new:5-3", 'invalid range 5-3 in "new:5-3"'),
                 ("new:0-3", 'invalid range 0-3 in "new:0-3"')]
        for value, msg in cases:
            with self.subTest(lines=value):
                m = valid_mapping()
                m["elements"][1]["implementation"][0]["lines"] = value
                self.assertMappingFails(m, 'elements[1].implementation[0]: "lines" ' + msg)

    def test_diff_hash_mismatch(self):
        m = valid_mapping()
        m["diffSha256"] = "0" * 64
        self.assertMappingFails(m, "diffSha256 does not match changes.diff (mapping was written for another diff")

    def test_diff_hash_malformed(self):
        m = valid_mapping()
        m["diffSha256"] = "abc"
        self.assertMappingFails(m, "diffSha256: must be a 64-character hex SHA-256")

    def test_diff_without_file_sections(self):
        self.assertFails(self.generate(diff="just some text\n"),
                         "changes.diff: no 'diff --git' file sections found")

    def test_all_errors_are_reported(self):
        code, _, err = self.run_tool(os.path.join(EXAMPLES, "invalid-mapping.json"),
                                     os.path.join(EXAMPLES, "changes.diff"),
                                     "-o", self.default_out)
        self.assertEqual(code, 1)
        self.assertIn('error: elements[1].tests[0]: missing "symbol"', err)
        self.assertIn('error: elements[2]: duplicate id "E1"', err)
        self.assertFalse(os.path.exists(self.default_out))

    def test_existing_output_untouched_on_error(self):
        with open(self.default_out, "w") as fh:
            fh.write("old")
        m = valid_mapping()
        m["version"] = 3
        code, _, _ = self.generate(m)
        self.assertEqual(code, 1)
        with open(self.default_out) as fh:
            self.assertEqual(fh.read(), "old")

    def test_usage_error_exits_2(self):
        code, _, err = self.run_tool("only-one-arg.json")
        self.assertEqual(code, 2)
        self.assertIn("usage:", err)


class WarningTests(GeneratorTestCase):
    """Warnings go to stderr with 'warning:' and generation still succeeds."""

    def assertWarning(self, result, expected, count):
        code, out, err = result
        self.assertEqual(code, 0, err)
        self.assertIn("warning: " + expected, err)
        self.assertIn("%d warnings)" % count, out)
        self.assertTrue(os.path.exists(self.default_out))

    def test_no_warnings(self):
        code, out, err = self.generate()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out.strip(), "Wrote %s (2 elements, 1 linked, 0 warnings)" % self.default_out)

    def test_file_not_in_diff(self):
        m = valid_mapping()
        m["elements"][1]["tests"].append(ref("src/Other.java", "x"))
        self.assertWarning(self.generate(m),
                         "elements[1] (E2) tests[1]: file src/Other.java not in diff", 1)

    def test_symbol_not_found(self):
        m = valid_mapping()
        m["elements"][1]["implementation"] = [ref("src/Foo.java", "unregister")]
        self.assertWarning(self.generate(m), 'elements[1] (E2) implementation[0]: '
                         'symbol "unregister" not found in src/Foo.java', 1)

    def test_symbol_matched_as_whole_word_only(self):
        m = valid_mapping()
        m["elements"][1]["implementation"] = [ref("src/Foo.java", "regist")]
        self.assertWarning(self.generate(m), 'elements[1] (E2) implementation[0]: symbol "regist" not found', 1)

    def test_symbol_found_in_removed_line_and_hunk_heading(self):
        m = valid_mapping()
        m["elements"][1]["implementation"] = [ref("src/Foo.java", "store")]
        m["elements"][1]["tests"] = [ref("src/Foo.java", "Foo")]  # only in the @@ heading
        code, _, err = self.generate(m, PARTIAL_DIFF)
        self.assertEqual(code, 0)
        self.assertNotIn("not found", err)

    def test_limited_context(self):
        self.assertWarning(self.generate(diff=PARTIAL_DIFF),
                         "diff has limited context for 1 file(s) (e.g. src/Foo.java); "
                         "use -U99999 for expandable files", 1)

    def test_no_linked_elements(self):
        m = {"version": 2, "elements": [element("E1", "# Only text\n")]}
        self.assertWarning(self.generate(m), "no linked elements", 1)

    def generate_with_lines(self, lines, symbol="register", diff=DIFF):
        m = valid_mapping()
        m["elements"][1]["implementation"] = [dict(ref("src/Foo.java", symbol), lines=lines)]
        return self.generate(m, diff)

    def test_lines_valid(self):
        for lines in ("new:2-6", "new:2", "old:2-3", "new:1,2-3", "new: 2 - 6"):
            with self.subTest(lines=lines):
                code, _, err = self.generate_with_lines(lines)
                self.assertEqual((code, err), (0, ""))

    def test_lines_not_in_diff(self):
        self.assertWarning(self.generate_with_lines("new:5-9"),
                           "elements[1] (E2) implementation[0]: lines new:5-9 not in the diff "
                           "of src/Foo.java", 1)

    def test_lines_outside_hunk_of_partial_diff(self):
        code, _, err = self.generate_with_lines("new:1-11", diff=PARTIAL_DIFF)
        self.assertEqual(code, 0)
        self.assertIn("warning: elements[1] (E2) implementation[0]: lines new:1-11 not in the diff", err)

    def test_lines_without_symbol(self):
        self.assertWarning(self.generate_with_lines("new:4-6"),
                           'elements[1] (E2) implementation[0]: symbol "register" not found in '
                           'lines new:4-6 of src/Foo.java', 1)

    def test_removed_line_only_on_old_side(self):
        # Old line 3 is "save(email);"; on the new side line 3 is the added String line.
        code, _, err = self.generate_with_lines("old:3", symbol="save")
        self.assertEqual((code, err), (0, ""))
        self.assertWarning(self.generate_with_lines("new:3", symbol="save"),
                           'elements[1] (E2) implementation[0]: symbol "save" not found in '
                           'lines new:3 of src/Foo.java', 1)

    def test_lines_on_missing_side_of_deleted_file(self):
        diff = ("diff --git a/src/Foo.java b/src/Foo.java\ndeleted file mode 100644\n"
                "--- a/src/Foo.java\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-class Foo {\n-}\n")
        code, _, err = self.generate_with_lines("new:1", symbol="Foo", diff=diff)
        self.assertEqual(code, 0)
        self.assertIn("lines new:1 not in the diff", err)

    def test_matching_diff_hash(self):
        import hashlib
        m = valid_mapping()
        m["diffSha256"] = hashlib.sha256(DIFF.encode("utf-8")).hexdigest().upper()
        code, _, err = self.generate(m)
        self.assertEqual((code, err), (0, ""))

    def test_deleted_file_matched_by_old_path(self):
        diff = ("diff --git a/src/Old.java b/src/Old.java\ndeleted file mode 100644\n"
                "--- a/src/Old.java\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-class Old {\n-}\n")
        m = valid_mapping()
        m["elements"][1] = element("E2", "x\n", impl=[ref("src/Old.java", "Old")])
        code, _, err = self.generate(m, diff)
        self.assertEqual((code, err), (0, ""))


class OutputTests(GeneratorTestCase):

    def test_default_output_next_to_mapping(self):
        sub = os.path.join(self.dir, "sub")
        os.mkdir(sub)
        m = os.path.join(sub, "mapping.json")
        with open(m, "w") as fh:
            json.dump(valid_mapping(), fh)
        d = self.write("changes.diff", DIFF)
        code, out, _ = self.run_tool(m, d)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(sub, "review.html")))
        self.assertIn(os.path.join(sub, "review.html"), out)

    def test_explicit_output_overwrites(self):
        target = os.path.join(self.dir, "out.html")
        with open(target, "w") as fh:
            fh.write("old")
        code, out, _ = self.generate(extra=("-o", target))
        self.assertEqual(code, 0)
        self.assertIn("Wrote %s " % target, out)
        self.assertFalse(os.path.exists(self.default_out))
        with open(target, encoding="utf-8") as fh:
            self.assertIn('id="mapping-data"', fh.read())

    def test_escaping_round_trip(self):
        m = valid_mapping()
        m["elements"][0]["text"] = "# Foo </script><script>alert(1)</script> & <b>x</b> /*META_JSON*/\n"
        code, _, err = self.generate(m)
        self.assertEqual(code, 0, err)
        with open(self.default_out, encoding="utf-8") as fh:
            html = fh.read()
        # Only the template's own script tags close a script element.
        with open(TEMPLATE, encoding="utf-8") as fh:
            self.assertEqual(html.count("</script>"), fh.read().count("</script>"))
        self.assertEqual(extract_block(html, "mapping-data"), m)
        with open(os.path.join(self.dir, "changes.diff"), encoding="utf-8", newline="") as fh:
            self.assertEqual(extract_block(html, "diff-data"), fh.read())
        meta = extract_block(html, "meta-data")
        self.assertEqual(meta["mappingFile"], "mapping.json")
        self.assertEqual(meta["diffFile"], "changes.diff")
        self.assertRegex(meta["generatedAt"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        for ph in make_review.PLACEHOLDERS[:2]:
            self.assertNotIn(ph, html.replace(m["elements"][0]["text"], ""))

    def test_non_ascii_kept(self):
        m = valid_mapping()
        m["elements"][0]["text"] = "# Café ✓ 日本\n"
        self.generate(m)
        with open(self.default_out, encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("Café ✓ 日本", html)
        self.assertEqual(extract_block(html, "mapping-data"), m)


class ExampleTests(GeneratorTestCase):

    def example(self, name):
        return os.path.join(EXAMPLES, name)

    def test_full_example(self):
        out = os.path.join(self.dir, "review.html")
        code, stdout, err = self.run_tool(self.example("mapping.json"), self.example("changes.diff"),
                                          "-o", out)
        self.assertEqual(code, 0, err)
        self.assertIn("(14 elements, 10 linked, 2 warnings)", stdout)
        self.assertIn('symbol "sendWelcomeEmail" not found', err)
        self.assertIn("file src/main/java/auth/UserRepository.java not in diff", err)
        self.assertNotIn("limited context", err)
        with open(out, encoding="utf-8") as fh:
            html = fh.read()
        with open(self.example("mapping.json"), encoding="utf-8") as fh:
            self.assertEqual(extract_block(html, "mapping-data"), json.load(fh))

    def test_partial_example(self):
        out = os.path.join(self.dir, "review.html")
        code, stdout, err = self.run_tool(self.example("mapping.json"), self.example("partial.diff"),
                                          "-o", out)
        self.assertEqual(code, 0, err)
        self.assertIn("warning: diff has limited context for 2 file(s)", err)
        self.assertIn("3 warnings)", stdout)

    def test_example_diffs_cover_parser_cases(self):
        with open(self.example("changes.diff"), encoding="utf-8") as fh:
            text = fh.read()
        files = {f["path"]: f for f in make_review.parse_diff(text)}
        auth = "src/main/java/auth/"
        self.assertTrue(files[auth + "EmailValidator.java"]["new"])
        self.assertTrue(files[auth + "LegacyPasswordHasher.java"]["deleted"])
        renamed = files[auth + "PasswordPolicy.java"]
        self.assertTrue(renamed["renamed"])
        self.assertEqual(renamed["old_path"], auth + "PasswordRules.java")
        self.assertTrue(files["src/main/resources/logo.png"]["binary"])
        self.assertIn("\\ No newline at end of file", text)
        self.assertTrue(all(make_review.is_complete(f) for f in files.values()))

    def test_example_hunk_counts_are_exact(self):
        """Each hunk's header counts match its body exactly, in both example diffs."""
        for name in ("changes.diff", "partial.diff"):
            with open(self.example(name), encoding="utf-8") as fh:
                lines = fh.read().split("\n")
            i = 0
            while i < len(lines):
                m = make_review.HUNK_RE.match(lines[i])
                i += 1
                if not m:
                    continue
                old = 1 if m.group(2) is None else int(m.group(2))
                new = 1 if m.group(4) is None else int(m.group(4))
                while i < len(lines) and lines[i][:1] in (" ", "+", "-", "\\") \
                        and not lines[i].startswith(("--- ", "+++ ")):
                    tag = lines[i][:1]
                    if tag in " -":
                        old -= 1
                    if tag in " +":
                        new -= 1
                    i += 1
                with self.subTest(diff=name, hunk=m.group(0)):
                    self.assertEqual((old, new), (0, 0))


class ParserTests(unittest.TestCase):

    def test_omitted_counts_mean_one(self):
        diff = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-x\n+y\n"
        [f] = make_review.parse_diff(diff)
        self.assertEqual(f["hunks"], [(1, 1, 1, 1)])
        self.assertTrue(make_review.is_complete(f))

    def test_removed_line_looking_like_header(self):
        diff = ("diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,1 @@\n"
                "--- not a header\n keep\n")
        [f] = make_review.parse_diff(diff)
        self.assertEqual(f["path"], "a.txt")
        self.assertIn("-- not a header", f["lines"])

    def test_quoted_path(self):
        diff = ('diff --git "a/dir/caf\\303\\251 x.txt" "b/dir/caf\\303\\251 x.txt"\n'
                'new file mode 100644\n--- /dev/null\n+++ "b/dir/caf\\303\\251 x.txt"\n'
                "@@ -0,0 +1 @@\n+hi\n")
        [f] = make_review.parse_diff(diff)
        self.assertEqual(f["path"], "dir/café x.txt")
        self.assertTrue(f["new"])

    def test_two_hunks_is_partial(self):
        diff = ("diff --git a/a b/a\n--- a/a\n+++ b/a\n@@ -1,1 +1,1 @@\n-a\n+b\n"
                "@@ -10,1 +10,1 @@\n-c\n+d\n")
        [f] = make_review.parse_diff(diff)
        self.assertFalse(make_review.is_complete(f))


if __name__ == "__main__":
    unittest.main()
