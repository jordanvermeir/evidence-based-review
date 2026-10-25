# Spec-to-Code Review (PoC)

Builds one **self-contained, offline HTML page** for reviewing a change set against its
specification. The spec appears on the left as raw Markdown. Clicking a linked passage shows
its **tests first, then its implementation**, as foldable GitHub-style diffs on the right.

```text
spec-review/
  template.html          generic viewer (no data; open a generated page instead)
  make-review.py         generator: validates inputs, injects them into the template
  examples/              sample inputs (see "Examples")
  tests/                 unittest suite for the generator
```

Requirements: Python 3.9+ (standard library only) and a current browser. There is no server,
no build step and no third-party code.

## Workflow

```bash
# In the reviewed repository:
git add -N .                                              # make new untracked files visible
git diff -U99999 BASE_COMMIT -- '*.java' > changes.diff   # full-context diff, prod + tests

# A coding agent writes mapping.json (format below).

python3 spec-review/make-review.py mapping.json changes.diff              # → review.html next to mapping.json
python3 spec-review/make-review.py mapping.json changes.diff -o out.html  # explicit output
```

Then double-click the generated page.

```text
usage: make-review.py MAPPING DIFF [-o OUT] [--template PATH]
```

| Exit code | Meaning |
|---|---|
| 0 | Page written. Warnings (`warning: …`) may have been printed. |
| 1 | Invalid input (`error: …`, with its location). Nothing is written. |
| 2 | Bad command-line usage. |

## Input 1: `mapping.json`

The mapping holds **the whole spec**, cut into ordered elements. Concatenating every `text`
with nothing in between must reproduce the spec exactly, so each element carries its own
newlines. An element may start or end mid-line.

```json
{
  "version": 2,
  "title": "User registration",
  "elements": [
    { "id": "E1", "text": "# User registration\n\nIntro text.\n\n- ", "tests": [], "implementation": [] },
    { "id": "E2", "text": "Email addresses **must** be unique.\n",
      "tests":          [{ "file": "src/test/java/auth/UserServiceTest.java", "symbol": "rejectsDuplicateEmail" }],
      "implementation": [{ "file": "src/main/java/auth/UserService.java",     "symbol": "register" }] }
  ]
}
```

- `version` must be `2`. `title` is optional (default `Spec review`).
- `id` must be unique and `text` non-empty. `tests` and `implementation` are arrays and may be
  empty. An element with both arrays empty is **unlinked**, such as a heading or intro text.
- `file` is the repo-relative path as it appears in the diff (the `b/` path, or the `a/` path
  for a deleted file). `symbol` is a method or class name, matched as a whole word.
- `lines` (optional, per reference) names the exact lines to show, as `side:ranges`:
  `"new:31-39"`, `"old:12-19"` (a deleted method only has old-side numbers) or several
  ranges such as `"new:10-20,40-55"`. When present it takes precedence over locating the
  symbol, and it works for any file type (YAML, SQL, Kotlin…). The symbol must still occur
  somewhere in those lines; that catches miscounted or wrong-side numbers. Get the numbers
  from a tool (e.g. `grep -n` on the checked-out file), not by counting diff lines.
- `diffSha256` (optional, top level) is the SHA-256 of the diff file the mapping was written
  for (`shasum -a 256 changes.diff`). A mapping and its diff are a 1:1 snapshot; with this
  field the generator refuses to combine a mapping with any other diff.
- Recommended granularity: one element per requirement sentence or bullet, with unlinked
  elements for the text in between.
- Unknown extra fields are ignored.

## Input 2: `changes.diff`

A unified git diff covering both production and test code. Use **`-U99999`** so each file
appears complete, which makes every line expandable in the viewer. Diffs with less context
are accepted with a warning. In that case the lines outside the hunks show as non-expandable
"not in diff" bars.

A mapped file that does not appear in the diff is reported as *not in diff* (probably
unchanged), never as unimplemented.

## What the generator checks

**Errors** (exit 1): missing or unreadable inputs or template; invalid JSON (with line and
column); wrong `version`; missing, empty or non-array `elements`; missing or wrongly typed
element fields; duplicate ids; malformed references or `lines`; a malformed or non-matching
`diffSha256`; a diff without any `diff --git` section.

**Warnings** (the page is still written, and the same list appears in the page):
- a referenced file is not in the diff;
- a symbol does not occur as a whole word anywhere in its file's diff;
- a reference's `lines` are not (all) in the diff on that side, or don't contain its symbol.
  The page then falls back to locating the symbol;
- the diff has limited context for some files;
- no element is linked.

## Using the page

- **Header:** Previous / Next step through linked passages. The counts show passages without
  tests or implementation and your review marks. `⚠ N warnings` opens a clickable list.
- **Left pane:** the spec exactly as written, with line numbers. Only ATX headings are bolded,
  and not inside code fences. Linked passages are tinted and can be clicked, or focused and
  activated with Enter or Space. The ✓ / ! markers in the gutter show review state.
- **Right pane:** the passage, its *Reviewed* / *Needs attention* toggle (click again to
  clear), then Tests and Implementation. Each reference opens on its whole method or class,
  overloads included, with annotations and Javadoc. The rest of the file sits behind bars with
  `↑ 20`, `↓ 20` and `Show all`; each bar says how many changed lines it hides. When a symbol's
  declaration can't be located, the view falls back to all changes with 3 lines of context.
- Review marks and fold state live only in memory and are lost on reload.

Links show where related changes are. They do not prove a requirement is correctly implemented
or fully tested.

### How symbols are located

References with valid `lines` skip this entirely: the page shows exactly those lines. For
all other references, a declaration is a whole-word occurrence of the symbol in code (not in a string or comment)
that is followed by `(` or preceded by `class` / `interface` / `enum` / `record` /
`@interface`, with a `{` before any `;`. Calls such as `service.register(x);` and abstract
methods therefore don't count. The new side is searched first, then the old side (for removed
code). The range runs from the preceding annotations and comments to the matching `}`. Brace
counting skips strings, char literals, text blocks and comments. This heuristic targets C-like
languages; for other languages the fallback view applies.

## Examples

```bash
python3 make-review.py examples/mapping.json examples/changes.diff                     # 2 warnings
python3 make-review.py examples/mapping.json examples/partial.diff -o examples/review-partial.html
python3 make-review.py examples/invalid-mapping.json examples/changes.diff              # fails
```

`examples/mapping.json` covers:

| Case | Where |
|---|---|
| Unlinked heading, intro, element ending mid-line | E1, E2 |
| Tests + implementation / implementation only / tests only (starts mid-line) | E3 / E4 / E5 |
| Overloads (`register` ×2), annotations, Javadoc, braces in strings and comments | E3 → `UserService.register` |
| Same file linked from several elements (independent fold state) | `UserService.java` in E3, E4, E7, E8, E9 |
| Renamed file, class symbol, Markdown table | E6 → `PasswordPolicy` |
| New files, file without trailing newline | E7 → `EmailValidator`, tests |
| Symbol with no mentions (warning + fallback) | E8 → `sendWelcomeEmail` |
| Symbol mentioned but never declared (fallback, highlighted) | E9 → `hashPassword` |
| Explicit `lines` on the new side | E7 → `EmailValidator.isValid` (`new:10-12`) |
| Deleted file, explicit `lines` on the old side | E10 → `LegacyPasswordHasher.hash` (`old:12-19`) |
| File not in diff | E11 → `UserRepository` |
| Fenced blocks containing `# not a heading` (``` and ~~~) | E12, E14 |
| `<b>` and `</script>` in spec and diff, rendered literally | E13 → `keepsDisplayNameLiteral` |

The diff also contains a binary file (`logo.png`). `partial.diff` is the same change set at
`-U3`. `invalid-mapping.json` has a duplicate id and a missing `symbol`.

## Tests

```bash
cd spec-review
python3 -m unittest discover tests
```

The suite covers every fatal error and warning, the output paths, `</script>` escaping (the
page parses back to the identical mapping and diff), the bundled examples, and exact hunk
counts in the example diffs.

The viewer is checked by hand against the acceptance criteria, using the generated example
pages in current Chrome, Edge, Firefox and Safari.

## Known limitations

- Quoted diff paths with escape sequences are only supported for simple cases.
- Symbol location is heuristic and aimed at C-like languages; use `lines` for anything else.
- No persistence, comments, syntax highlighting or Markdown rendering. These are out of
  scope for the PoC.
