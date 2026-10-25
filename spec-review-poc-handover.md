# Spec-to-Code Review — PoC Implementation Spec

## 1. Goal
Build a small local tool that produces a **self-contained, interactive review page** for one change set. The page shows a specification as raw Markdown on the left. On the right it shows the **tests first, then the implementation** linked to the selected passage, as expandable GitHub-style diff views.

This is a proof of concept, not a production app.

The tool has two parts:

1. **`template.html`**: a generic viewer (HTML + CSS + vanilla JS) containing no data.
2. **`make-review.py`**: a command that validates one `mapping.json` + `changes.diff` pair and injects them into a copy of the template. The result is a single `review.html` that opens by double-click, works offline, and can be shared as one file.

A **coding agent** produces `mapping.json` and `changes.diff` outside this tool. The tool only consumes them.

## 2. Deliverables

```text
spec-review/
  template.html          # generic viewer; not meant to be opened directly
  make-review.py         # generator, Python 3.9+, standard library only
  examples/
    mapping.json         # sample spec + links (covers the edge cases in §10)
    changes.diff         # sample full-context diff
    partial.diff         # sample limited-context diff (triggers warning)
    invalid-mapping.json # sample that must fail validation
  tests/
    test_make_review.py  # unittest, stdlib only
  README.md              # usage: how to produce inputs and run the generator
```

No framework, bundler, server, database, authentication, CDN or third-party packages.

## 3. Workflow

```bash
# 1. In the reviewed repo: make new untracked files visible to git diff
git add -N .
# 2. Full-context diff (every changed file complete) for production + test code
git diff -U99999 BASE_COMMIT -- '*.java' > changes.diff
# 3. Agent writes mapping.json (see §4)
# 4. Generate the review page
python3 spec-review/make-review.py mapping.json changes.diff            # → review.html next to mapping.json
python3 spec-review/make-review.py mapping.json changes.diff -o out.html
# 5. Double-click the generated page
```

## 4. Input: `mapping.json`

`mapping.json` contains the **whole spec**, split into ordered elements. There is no separate spec file.

```json
{
  "version": 2,
  "title": "User registration",
  "elements": [
    {
      "id": "E1",
      "text": "# User registration\n\nUsers sign up with an email address.\n\n",
      "tests": [],
      "implementation": []
    },
    {
      "id": "E2",
      "text": "- Email addresses **must** be unique.\n",
      "tests": [
        {"file": "src/test/java/auth/UserServiceTest.java", "symbol": "rejectsDuplicateEmail"}
      ],
      "implementation": [
        {"file": "src/main/java/auth/UserService.java", "symbol": "register"}
      ]
    }
  ]
}
```

Rules:

| Field | Required | Rule |
|---|---|---|
| `version` | yes | Must be `2`. |
| `title` | no | String shown in the page header. Default: `Spec review`. |
| `elements` | yes | Non-empty array, in spec order. |
| `elements[].id` | yes | Non-empty string, unique across elements. |
| `elements[].text` | yes | Non-empty string of raw Markdown. **Concatenating all `text` values with nothing in between must reproduce the original spec exactly.** Elements carry their own newlines, and an element may end mid-line. |
| `elements[].tests` | yes | Array of references (may be empty). |
| `elements[].implementation` | yes | Array of references (may be empty). |
| reference `.file` | yes | Repo-relative path. Must equal the diff's `b/` path (or the `a/` path for deleted files). |
| reference `.symbol` | yes | Method or class name, matched as a whole word (§7). Advisory, not a guarantee. |

- The whole spec must be covered, including headings, intro text and background. Elements with both lists empty are **unlinked**. All others are **linked**.
- Recommended granularity, as guidance for the agent: one element per requirement sentence or bullet, with unlinked elements for the text in between.
- Unknown extra fields are ignored.
- Reference order within each list is preserved.

## 5. Input: `changes.diff`

- Standard unified Git patch format, generated with **`-U99999`** so that each changed file appears complete as one hunk. This is what enables expanding (§8).
- It must include both production and test changes. New untracked files are only included when they are intent-to-add (`git add -N`) or staged.
- An unchanged file or method is not in the diff, even if mapped. The viewer reports this as "not in diff", never as "unimplemented".
- Diffs with limited context (plain `git diff`, `-U3`, `-U20`) are accepted with a warning (§6, §8.4).

The parser must handle:
- `diff --git a/X b/Y` file headers, `---` / `+++`, `@@ -a,b +c,d @@ optional heading`
- `new file mode` / `--- /dev/null` (all lines added), `deleted file mode` / `+++ /dev/null` (all lines removed)
- `rename from` / `rename to`, `similarity index`, `index …` lines
- `Binary files … differ` (show "binary file, no preview")
- `\ No newline at end of file` (not counted as a code line)
- Hunk counts that are omitted (`@@ -1 +1 @@` means a count of 1)
- Known limitation: quoted paths with escape sequences are only supported for simple cases.

## 6. Generator: `make-review.py`

```text
usage: make-review.py MAPPING DIFF [-o OUT] [--template PATH]
  MAPPING          path to mapping.json
  DIFF             path to changes.diff
  -o, --output     output HTML path (default: review.html in MAPPING's directory)
  --template       template path (default: template.html next to the script)
```

Behaviour:
1. Read both inputs as UTF-8.
2. Validate them (see below). Errors go to stderr, prefixed `error:`, and the script exits with code **1** without writing anything. Warnings go to stderr, prefixed `warning:`, and generation continues.
3. Inject the data into the template and write the output, overwriting any existing file. Print `Wrote <path> (<n> elements, <k> linked, <w> warnings)` and exit **0**.
4. Argument/usage errors exit with code **2** (argparse default).

**Errors** (fatal):
- An input file is missing or unreadable, or the template is missing, or the template has no placeholders.
- Invalid JSON, reported with line and column.
- `version` ≠ 2, `elements` missing, empty or not an array.
- An element is missing `id` / `text` / `tests` / `implementation`, has a wrong type or empty `text`, or has a duplicate `id`.
- A reference is not an object, or has a missing/empty `file` or `symbol`.
- The diff contains no `diff --git` file sections.

Each error message names the location, e.g. `error: elements[3].tests[0]: missing "symbol"`.

**Warnings** (non-fatal):
- `elements[i] (E7) tests[0]: file src/…/Foo.java not in diff`
- `elements[i] (E7) implementation[1]: symbol "register" not found in src/…/UserService.java`. This fires when the symbol doesn't appear as a whole word in any diff line of that file (headers, context, added or removed lines).
- `diff has limited context for N file(s) (e.g. src/…/Foo.java); use -U99999 for expandable files`. See §8.4 for detection.
- `no linked elements` (every element has empty lists).

**Injection.** The template contains exactly these three placeholders:

```html
<script type="application/json" id="mapping-data">/*MAPPING_JSON*/</script>
<script type="application/json" id="diff-data">/*CHANGES_DIFF*/</script>
<script type="application/json" id="meta-data">/*META_JSON*/</script>
```

- `MAPPING_JSON` is the re-serialised mapping. `CHANGES_DIFF` is the diff as a JSON string literal. `META_JSON` is `{"generatedAt": ISO-8601, "mappingFile": basename, "diffFile": basename}`.
- All three are serialised with `json.dumps(..., ensure_ascii=False)`, and then `<`, `>` and `&` are replaced with `<`, `>` and `&`. This way content such as `</script>` can never break out of the script element.
- Replacement is plain string substitution, never regex-based on the data.

## 7. Locating a symbol in a file (viewer)

Input: the parsed rows of one file (§8.1) and a `symbol`.

1. **Mentions:** rows whose text contains `symbol` as a whole word (`(?<![\w$])symbol(?![\w$])`, regex-escaped).
2. **Declaration candidates:** mentions where the symbol is immediately followed by optional whitespace and `(`, or preceded by `class`, `interface`, `enum`, `record` or `@interface`, **and** where scanning forward from the symbol (across rows) a `{` appears before any `;`. This excludes calls (`service.register(x);`) and abstract/interface declarations.
   - Search the **new side** first (context + added rows). If nothing is found, search the **old side** (context + removed rows), e.g. for a removed method.
3. **Range of each declaration:**
   - **Start:** the declaration row, extended upwards over directly preceding annotation rows (`@Something…`) and Javadoc/comment rows (`/** … */`, `//`).
   - **End:** the row containing the `}` that matches the first `{`. Brace counting runs over the side being searched. It skips braces inside `"…"`, `'…'`, text blocks (`"""…"""`), `// …` line comments and `/* … */` block comments, as far as practical.
   - If the matching brace is not found (truncated hunk), the range ends at the last row of that hunk.
4. Every declaration found becomes a visible range. This covers overloads.
5. The range is mapped to **unified rows**: from the first unified row to the last, including interleaved removed/added rows.

Outcomes:
- **Declarations found:** the initial view shows those ranges (§8.2).
- **Mentions but no declaration:** the fallback view (§8.3) is shown, mention rows are highlighted, and a note says "declaration of `symbol` not located; showing all changes".
- **No mentions:** the fallback view is shown with the warning "symbol `symbol` not found in this file; showing all changes".

Brace matching is a heuristic aimed at C-like languages (Java, Kotlin, C#, JS/TS, Go…). For other languages the fallback applies, and that is acceptable for the PoC.

## 8. Diff view and folding (viewer)

### 8.1 Model
Each file is parsed into **unified rows**: `{type: context|add|del, oldNo, newNo, text}`. Hunk boundaries are kept. Between two hunks, or before the first hunk if it doesn't start at line 1, there is a **gap** that isn't in the diff.

### 8.2 Initial view per mapping entry
- **Visible:** the declaration ranges from §7.
- **Folded:** everything else in the file. Each folded stretch is replaced by a bar:
  `⋯ 41 lines hidden (3 changed) ⋯   [↑ 20]  [↓ 20]  [Show all]`
  - `↑ 20` reveals 20 rows at the bottom of the stretch (above the next visible block), and `↓ 20` reveals 20 rows at the top. `Show all` reveals the whole stretch.
  - The "(N changed)" count is the number of add/del rows hidden in that stretch. It is omitted when zero, so changes outside the method are never hidden silently.
  - Stretches of ≤ 3 rows are not folded; they're simply shown.
- A per-file `Expand all` / `Collapse to symbol` toggle sits in the file header.
- Fold state lives in each entry. The same file linked from two entries, or twice in one element, has independent views.

### 8.3 Fallback view (GitHub default)
- Every add/del row plus 3 context rows on each side is visible. Everything else is folded with the same bars as §8.2.
- New and deleted files show in full, up to 400 rows, beyond which the rest is folded.

### 8.4 Limited-context diffs
- A file is **complete** if it's new, deleted, or has exactly one hunk whose old and new start are both 1 (or 0 for an empty side). Otherwise it's **partial**.
- In partial files, gaps render as a non-expandable bar: `⋯ lines 58–140 not in diff ⋯`. Folded stretches *inside* hunks still expand normally.
- The file header shows a small "limited context" badge.

### 8.5 Rendering
- Two line-number gutters (old, new), then a `+` / `-` / space marker, then code.
- Added rows have a green background and removed rows a red one, distinguishable in both light and dark themes and not by colour alone (the marker column).
- Rows in the symbol range get a subtle left border. Mention rows (fallback) are highlighted.
- The `@@` header is shown above each hunk in muted text, including its heading.
- Code is monospace and is not wrapped; it scrolls horizontally inside the file block. Tabs are rendered at a width of 4.
- **All diff, spec and mapping text is inserted via `textContent` / text nodes, never `innerHTML`.**

## 9. Viewer UI (`template.html`)

On load, the viewer parses the three JSON script blocks. If the placeholders are still present (template opened directly), it shows only: "This is the viewer template. Generate a review page with `python3 make-review.py mapping.json changes.diff`." If parsing fails, it shows the error message.

**Layout:** a header bar, then two panes side by side. Each pane scrolls independently. Below 900 px width the panes stack, spec on top.

**Header**
- Title and generation metadata (time, input file names).
- Navigation: `◀ Previous` · `3 / 12` · `Next ▶`. This moves through linked elements only, in document order, and scrolls the left pane to the selection.
- Counts: `12 linked passages · 2 without tests · 1 without implementation · Reviewed 4 · Needs attention 1`.
- A global warnings indicator (`⚠ 3 warnings`) that expands into a list. The list holds the same file and symbol warnings as the generator, each clickable to select its element.
- A permanent disclaimer: *"Links show where related changes are. They do not prove a requirement is correctly implemented or fully tested."*

**Left pane: spec**
- The concatenated element texts, shown **raw**: every character as in the source, in a monospace font, with soft wrapping and line numbers counted over the whole spec.
- Light styling only:
  - Lines starting with `#` (ATX headings) are bold. This is not applied inside fenced code blocks (```` ``` ```` / `~~~`), which are tracked while scanning.
  - No other Markdown is interpreted, and no characters are added or removed.
- Linked elements are tinted and clickable (also with Enter or Space when focused). The selected element has a stronger tint and an outline. An element can start or end mid-line; highlights are inline spans.
- Unlinked elements are muted but still readable, and are not clickable.
- A small gutter marker on linked elements shows their review status (none / ✓ / !).
- On load, the first linked element is selected.

**Right pane: selected element**
1. Element id, the element text (raw, monospace) and a review toggle: `Reviewed` / `Needs attention`. Clicking the active state again clears it. State is in memory only and lost on reload.
2. Neutral badges where applicable: `no tests linked`, `no implementation linked`.
3. **Tests** section, then the **Implementation** section, always in that order. Within each section, references keep the mapping order. An empty section shows "None linked."
4. Each reference is a collapsible file block. Its header shows:
   - the file path, symbol and status badges (`new file`, `deleted file`, `renamed`, `limited context`, `binary`);
   - the expand/collapse toggle (§8.2);
   - any warning for that reference.

   The body is the diff view (§8).
5. If the reference's file is not in the diff, a single row reads: *"`path` is not in the diff. It may be unchanged in this change set."* There's no code panel.

## 10. Example fixtures

`examples/` must exercise at least:
- Unlinked elements: heading, intro and an element that ends mid-line.
- An element with both tests and implementation, an element with tests only, and one with implementation only.
- A reference to a file absent from the diff (an unchanged method).
- A symbol with no mentions in its file, and a symbol mentioned but never declared (fallback with highlights).
- A new file, a deleted file, a renamed file.
- Overloaded methods (two declarations shown).
- One file linked from two elements (independent fold state).
- Annotations and Javadoc above a method, and braces inside strings and comments within a method.
- Spec content that is Markdown-heavy (a table, a fenced code block containing `# not a heading`, inline formatting), shown raw.
- A diff line containing `</script>` and HTML such as `<b>` (it must render literally).
- `partial.diff`: the same change set at `-U3`.
- `invalid-mapping.json`: a duplicate id and a missing `symbol`.

Fixture diffs are hand-written and must have correct hunk line counts.

## 11. Testing

`tests/test_make_review.py` (unittest) covers:
- Each fatal error from §6, with exit code 1 and nothing written.
- Each warning from §6, with exit code 0.
- The default output path and `-o`.
- Escaping: a generated page containing a diff with `</script>` can be parsed back to the identical mapping and diff.
- Generating from the bundled examples.

Viewer: a manual check against the acceptance criteria using the generated example pages in current Chrome, Edge, Firefox and Safari.

## 12. Acceptance criteria

1. `python3 make-review.py examples/mapping.json examples/changes.diff` writes `examples/review.html`. Opening it by double-click works offline, with no server.
2. The left pane shows the complete spec raw, character-for-character equal to the concatenated element texts.
3. Selecting a linked passage shows its tests first and its implementation second.
4. Each reference initially shows the whole linked method or class. The rest of the file is behind expand bars that reveal 20 lines or everything, and the bars report hidden changed lines.
5. Added and removed lines are visually distinct, with old and new line numbers.
6. A referenced file absent from the diff shows "not in diff", not "unimplemented". A symbol that can't be located shows a warning plus the fallback view.
7. Invalid input makes the generator fail with a located error message. Non-fatal problems are printed as warnings and also shown in the page.
8. A limited-context diff generates a page with a warning, and gaps are shown as non-expandable "not in diff" bars.
9. Previous/Next moves through linked passages. The counts and the Reviewed / Needs attention toggles work (in memory).
10. No diff or spec content is ever interpreted as HTML.

## 13. Non-goals

AI analysis; generating mappings inside the tool; repository access from the generator or viewer; repository indexing; Markdown rendering; syntax highlighting; persistence of review state; comments; multi-user review; authentication; GitHub/GitLab API integration; deployment or hosting; file picker or localhost auto-load for the template; keyboard shortcuts beyond basic focus/Enter.

## 14. Implementation order

1. Write the fixtures (§10).
2. `make-review.py`: validation, warnings, injection, plus the unit tests.
3. Template: data loading, template-not-generated message, layout, raw spec pane with element highlighting and selection.
4. Diff parser and unified-row model, including partial diffs.
5. Symbol location (§7) and folding with expand bars (§8).
6. Right pane wiring (tests before implementation), badges, warnings list, navigation, counts, review toggles.
7. README and a manual cross-browser pass against §12.
