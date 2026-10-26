"""Generate datasheets/index.yaml from the extracted doc-IRs.

Deterministic inputs only: each <PART>.doc.textproto's metadata and its first three
pages of text blocks. Never reads the PDF. Fields that require judgment (kind,
the curated `covers` list) are emitted as best-effort with a `review:` marker so a
human correction is visible rather than silent.
"""
import os, re, sys, json, hashlib

# Corpus root: the volume that holds <vendor>/<part>/ PDFs and doc-IR (not this repo).
# Set AGNI_DATASHEET_ROOT, or pass argv[4] on the command line.
ROOT = ""


def resolve_corpus_root(override: str | None = None) -> str:
    if override:
        return os.path.abspath(override)
    env = os.environ.get("AGNI_DATASHEET_ROOT")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    raise SystemExit(
        "Set AGNI_DATASHEET_ROOT to the corpus directory (PDFs + doc-IR), "
        "or pass the corpus path as argv[4]."
    )

# Vendor literature numbers. TI: 4 letters + 3-4 alnum (SLLSF80B, SNVSBP4D, SBVS050M).
DOCNUM_PATTERNS = [
    # TI literature number: S + 3 letters + 3-5 alnum, and it MUST contain a digit.
    # Without the digit lookahead this matched plain English words on the cover page
    # ("SAWTOOTH", "STORAGE", "STANDBY" all passed as doc numbers).
    re.compile(r"\b(S[A-Z]{3}(?=[A-Z0-9]*[0-9])[A-Z0-9]{3,5})\b"),
    re.compile(r"\b(Cat\.No\.[A-Z0-9-]+)\b", re.I),        # Murata
    re.compile(r"\b(DS00\d{4}[A-Z]?)\b"),                  # Microchip
    # Infineon / Cypress: "Document Number: 002-23881". Anchored on the label so a bare
    # 002-NNNNN elsewhere on the page cannot be mistaken for the literature number.
    re.compile(r"Document Number:\s*([0-9]{3}-[0-9]{4,6})", re.I),
]
DATE_RANGE = re.compile(
    r"([A-Z]+ \d{4})\s*[-–]\s*REVISED\s+([A-Z]+ \d{4})", re.I)
DATE_ONE = re.compile(r"\b([A-Z]{3,9} \d{4})\b")
REV_NXP = re.compile(r"\bRev\.?\s*([0-9]+(?:\.[0-9]+)?)\b", re.I)

# A part-number-ish token. The leading-digit group is required for Marvell-style
# numbers (88Q5152), and the alpha run must allow ONE letter for Infineon/Cypress
# flash (S25FS128S, S28HS01GT) -- a {2,6} floor silently dropped that whole family.
PARTTOK = re.compile(
    r"\b([0-9]{0,3}[A-Z]{1,6}[0-9][A-Z0-9]{1,14}(?:[-/][A-Z0-9]{1,8})*)\b")
NOISE = {"AEC", "IEC", "ESD", "HBM", "CDM", "ROHS", "REACH", "USB", "SPI", "I2C",
         "CAN", "LIN", "PDF", "MHZ", "KHZ", "GHZ"}


def pages_text(path, upto=3, per=48):
    """Text blocks for the first `upto` pages, as {pageno: [text, ...]}."""
    out, pageno = {}, 0
    with open(path, errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("pages {"):
                pageno += 1
                if pageno > upto:
                    break
                out[pageno] = []
                continue
            if pageno and len(out.get(pageno, [])) < per:
                m = re.match(r'text:\s*"(.*)"\s*$', s)
                if m:
                    t = m.group(1).replace('\\"', '"').replace("\\\\", "\\").strip()
                    if t:
                        out[pageno].append(t)
    return out


def top_meta(path):
    m = {}
    with open(path, errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("pages {"):
                break
            mm = re.match(r'(\w+):\s*"?([^"\n]*?)"?\s*$', s)
            if mm:
                m[mm.group(1)] = mm.group(2)
    return m


def pick_docnum(blocks, path=None):
    """Literature number, preferring the cover page, falling back to the whole document.

    The cover page is where most vendors print it, so it is tried first. But Infineon and
    Cypress print theirs only in the revision-history table at the BACK (S28HS01GT carries
    "Document Number: 002-23881" on page 9 of 10), so a cover-only scan left those entries
    with no doc_number at all and nothing to cite a transcription against.
    """
    for b in blocks:
        for pat in DOCNUM_PATTERNS:
            hit = pat.search(b)
            if hit:
                return hit.group(1)
    if not path:
        return None
    # The fallback uses ONLY the label-anchored patterns ("Document Number:", "Cat.No."),
    # never the bare TI shape. Given a whole document to scan, that unanchored regex has
    # thousands of chances to hit a register or signal name: it matched "SLPCTL0" deep in
    # the Microchip PHY sheet and reported it as the literature number. TI prints its
    # number on the cover, so it never needs the fallback anyway.
    anchored = [p for p in DOCNUM_PATTERNS if ":" in p.pattern or "\\." in p.pattern]
    with open(path, errors="replace") as fh:
        for line in fh:
            if "text:" not in line:
                continue
            for pat in anchored:
                hit = pat.search(line)
                if hit:
                    return hit.group(1)
    return None


def pick_dates(blocks):
    for b in blocks:
        m = DATE_RANGE.search(b)
        if m:
            return m.group(1).title(), m.group(2).title()
    for b in blocks:
        m = REV_NXP.search(b)
        if m:
            return None, f"Rev. {m.group(1)}"
    for b in blocks:
        m = DATE_ONE.search(b)
        if m and not m.group(1).upper().startswith(("PAGE",)):
            return m.group(1).title(), None
    return None, None


SKIP_TITLE = ("1 features", "features", "description", "general description",
              "contents", "note", "product", "www.", "order", "technical",
              "the ", "-", "·", "*", "complies", "suffix", "actual")


def pick_title(blocks, base):
    """The product title: prefer a block that STARTS with the part designation.

    Scoring on length alone picked body prose ("The MPQ2177 requires a minimal
    number of...") over the real title, because datasheet body sentences are longer
    than titles. A vendor product title almost always leads with the part number.
    """
    prefix = re.sub(r"[^A-Z0-9]", "", base.upper())[:4]
    best = None
    for i, b in enumerate(blocks[:16]):
        if len(b) < 18 or len(b) > 190:
            continue
        low = b.lower()
        if low.startswith(SKIP_TITLE):
            continue
        if re.match(r"^[\d\W]+$", b):
            continue
        lead = re.sub(r"[^A-Z0-9]", "", b.upper())[:4]
        score = 0
        if prefix and lead.startswith(prefix[:3]):
            score += 300          # leads with the part designation
        if prefix and prefix[:3] in b.upper():
            score += 60           # at least mentions it
        score += max(0, 90 - len(b)) // 10   # mild preference for concision
        score -= i                            # earlier blocks win ties
        if best is None or score > best[0]:
            best = (score, b)
    return best[1] if best else None


def expand_slashes(tokens):
    """Expand vendor shorthand into explicit part numbers.

    "MAX20402/MAX20403" -> both. "LAN8670/1/2" -> LAN8670, LAN8671, LAN8672.
    A trailing fragment shorter than the stem is a digit-suffix shorthand, so it
    inherits the leading part's prefix.
    """
    out = []
    for t in tokens:
        if "/" not in t:
            out.append(t)
            continue
        parts = t.split("/")
        head = parts[0]
        out.append(head)
        for frag in parts[1:]:
            if re.match(r"^[A-Z]", frag) and len(frag) >= len(head) - 1:
                out.append(frag)                       # a full part number
            elif frag.isdigit() and len(frag) < len(head):
                out.append(head[: len(head) - len(frag)] + frag)   # digit shorthand
            # Anything else (e.g. the "323SK" of "DSO223/323SK", where the fragment
            # replaces a MIDDLE run rather than a tail) is NOT expanded. Guessing
            # there fabricated part numbers that no sheet names ("D323SK"), which is
            # worse than an incomplete list in an index people will trust.
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


# A line that DECLARES the document's own scope, as opposed to merely mentioning parts.
# Deliberately narrow. The first version of family_runs accepted any line naming two or
# more prefix-matching parts, and that over-collected badly: datasheets routinely list
# cousins, EVM boards and wildcards together ("TMP116" on the TMP117 sheet, LMQ61460EVM,
# MSP430FR4xx, and for one Kyocera catalog all 60 frequency variants). Covering-scope is a
# claim the document makes about ITSELF, so only a self-declaring line is trusted.
TITLE_DECL = re.compile(r"Document Title:", re.I)


def family_runs(path, base, min_members=2):
    """Family lists from a line where the document declares its own title/scope.

    Some vendors print the full family ONLY in back matter. S28HS01GT names four siblings
    on its cover but all six in the page-9 revision table, on a line beginning
    "Document Title: S28HS256T/S28HS512T/S28HS01GT/S28HL256T/S28HL512T/S28HL01GT".

    Three guards: the line must be a scope DECLARATION (TITLE_DECL), each candidate must
    share the dir's prefix, and the line must name at least `min_members` such parts.
    """
    prefix = re.sub(r"[^A-Z0-9]", "", base.upper())[:3]
    if not prefix:
        return []
    found = []
    with open(path, errors="replace") as fh:
        for line in fh:
            if "text:" not in line or not TITLE_DECL.search(line):
                continue
            toks = [t for t in PARTTOK.findall(line.upper())
                    if t not in NOISE and t.startswith(prefix)]
            expanded = expand_slashes(toks)
            if len({re.sub(r"[^A-Z0-9]", "", t) for t in expanded}) >= min_members:
                found.extend(expanded)
    return found


def pick_covers(blocks, base, path=None):
    """Part numbers the sheet itself names, biased to the dir's family prefix."""
    # Prefix off the part-dir name itself, not its leading ALPHA run: an alpha-run
    # prefix degenerates to "S" for S25FS128S (matching every unrelated S-part) and
    # to "" for 88Q5152. The first three characters of the dir name behave for both.
    prefix = re.sub(r"[^A-Z0-9]", "", base.upper())[:3]
    seen, ordered = set(), []
    # 20 blocks, not 12: on the AD2428 and MAX20403 sheets the family header sits at
    # block 12-15, so a 12-block window found only the dir's own part and the entry
    # silently fell back to a single-part list.
    for b in blocks[:20]:
        # A comma/slash separated run on one line is the family header.
        for t in PARTTOK.findall(b.upper()):
            if t in NOISE or t in seen:
                continue
            if prefix and t.startswith(prefix):
                seen.add(t)
                ordered.append(t)
    ordered = expand_slashes(ordered)
    # Then merge any family run found deeper in the document (back-matter revision tables).
    # Appended AFTER the cover scan so the cover's ordering is preserved and the deeper
    # scan only ever ADDS siblings it missed.
    if path:
        # Rebuild the seen-set from the EXPANDED list. `seen` still holds the raw cover
        # tokens, so "AD2426/AD2427/AD2428" is in it while the expanded AD2426/7/8 are not,
        # and merging against it re-added all three as duplicates.
        seen = {re.sub(r"[^A-Z0-9]", "", t) for t in ordered}
        for t in family_runs(path, base):
            n = re.sub(r"[^A-Z0-9]", "", t)
            if n not in seen:
                seen.add(n)
                ordered.append(t)
    # Drop an "x"-wildcard family label from covers (TCAN114X-Q1, TPDXE05U06); it is
    # a family NAME, not a part, and it is recorded separately as `family`.
    ordered = [t for t in ordered if not re.search(r"[0-9]X[0-9-]|X[0-9]{2}", t)]
    # Any leftover slash token is shorthand expand_slashes declined to guess at.
    ordered = [t for t in ordered if "/" not in t]
    # Collapse punctuation-only duplicates, keeping the printed form: the same sheet
    # yields both "TCAN1144-Q1" and "TCAN1144Q1" across blocks.
    bynorm = {}
    for t in ordered:
        n = re.sub(r"[^A-Z0-9]", "", t)
        if n not in bynorm or len(t) > len(bynorm[n]):
            bynorm[n] = t
    ordered = [t for t in ordered if bynorm.get(re.sub(r"[^A-Z0-9]", "", t)) == t]
    if not ordered:
        # No family header found on the cover: the sheet is single-part, so the dir
        # name is the best available designation. Recorded rather than left blank so
        # a reader can tell "one part" from "extraction found nothing".
        ordered = [base.upper()]
    return ordered


def ordering_variants(path, covers, limit=40):
    """Ordering codes the sheet names, i.e. a covered part plus a package/grade tail.

    These are what a BOM actually carries (AD2428WCCSZ, not AD2428), and therefore
    what a PartSpec must key on for the exact-match param join to hit.
    """
    if not covers:
        return []
    bases = set()
    for c in covers:
        n = re.sub(r"[^A-Z0-9]", "", c.upper())
        bases.add(n)
        # A family label carrying an automotive grade suffix ("TPS746-Q1") is not a
        # prefix of its own ordering codes ("TPS74615PQWDRVRQ1"), so the grade tail is
        # stripped for matching too. Without this every -Q1 family reported zero
        # variants, which is exactly the family whose parts sit on these boards.
        stripped = re.sub(r"Q1$", "", n)
        if stripped and stripped != n and len(stripped) >= 5:
            bases.add(stripped)
    bases = sorted(bases, key=len, reverse=True)
    found = {}
    with open(path, errors="replace") as fh:
        for line in fh:
            if "text:" not in line:
                continue
            for t in PARTTOK.findall(line.upper()):
                flat = re.sub(r"[^A-Z0-9]", "", t)
                for b in bases:
                    if flat != b and flat.startswith(b) and len(flat) > len(b) + 1:
                        found[t] = found.get(t, 0) + 1
                        break
            if len(found) > 400:
                break
    covnorm = {re.sub(r"[^A-Z0-9]", "", c.upper()) for c in covers}
    out = []
    for t, _ in sorted(found.items(), key=lambda kv: (-kv[1], kv[0])):
        # A family header ("AD2426/AD2427/AD2428", "AD2426/7/8") is not an ordering
        # code. One slash is kept because Maxim really does write them that way
        # ("MAX20403AFLA/VY"); two or more means a list of parts.
        if t.count("/") >= 2:
            continue
        # One slash is ambiguous: "MAX20403AFLA/VY" is a package suffix (keep) but
        # "AD2427/AD2428" is a two-part list (drop). Decide by whether a fragment
        # after the first names a covered part or repeats the family prefix.
        if "/" in t:
            head, frags = t.split("/")[0], t.split("/")[1:]
            drop = False
            for f in frags:
                fn = re.sub(r"[^A-Z0-9]", "", f)
                if fn in covnorm or any(fn.startswith(b[:3]) for b in bases):
                    drop = True
                    break
                # Tail-substitution shorthand: "DP83867IR/CR" means DP83867IR AND
                # DP83867CR. Detected by swapping the fragment onto the head's tail
                # and asking whether that yields a part the sheet covers. This keeps
                # genuine package suffixes ("LM1117DT-ADJ/NOPB", "...AFLA/VY"),
                # which produce no covered part when swapped.
                hn = re.sub(r"[^A-Z0-9]", "", head)
                if len(fn) < len(hn) and (hn[: len(hn) - len(fn)] + fn) in covnorm:
                    drop = True
                    break
            if drop:
                continue
        # A covered part is not a variant of itself. Reachable because the -Q1 strip
        # above makes "TPS746-Q1" a prefix-match against base "TPS746".
        if re.sub(r"[^A-Z0-9]", "", t) in covnorm:
            continue
        out.append(t)
    return out[:limit]


ELEC = re.compile(
    r"electrical characteristics|recommended operating conditions"
    r"|absolute maximum ratings|dc characteristics|ac characteristics"
    r"|dc electrical|ac electrical|electrical specifications?"
    r"|operating conditions|power consumption|current consumption"
    r"|standard specifications?|timing (?:characteristics|specifications?|requirements)",
    re.I)

# A table header cell that carries a UNIT in parentheses, e.g. "HL-T Current (mA)",
# "Supply Voltage (V)", "Rise Time (ns)". Units are vendor-independent in a way that
# section headings are not.
UNIT_CELL = re.compile(
    r"\((?:[munpkKM]?(?:A|V|s|F|H|Hz|W|Ohm|Ω)|deg\s*C|°C|%|dB|ppm)\)", re.I)
# The classic limits header. Any two of these in one table means a parameter table.
LIMIT_WORDS = re.compile(r"\b(min|max|typ|typical|minimum|maximum|unit|units|symbol"
                         r"|parameter|conditions?|rating)\b", re.I)


def has_electrical(path):
    """Whether the document carries a parameter table worth transcribing.

    Two independent detectors, because heading text alone is not reliable. Keying only on
    "electrical characteristics" / "recommended operating conditions" / "absolute maximum
    ratings" produced a FALSE NEGATIVE on S28HS01GT, which carries a real supply-current
    table ("Operation | HL-T Current (mA) | HS-T Current (mA)", 10/75/156/50/0.014 ...)
    under none of those headings. A flag that says "no values here" about a document that
    has values is the same defect class as a check that passes without evaluating, so it
    is detected structurally as well as lexically:

      1. a recognised section heading (list broadened, still vendor-flavoured), OR
      2. a TABLE whose cells carry a parenthesised unit, or two-plus limits-header words
         (Symbol / Min / Typ / Max / Unit / Parameter) together with a number.

    Detector 2 is the durable one: units and Min/Typ/Max survive translation and vendor
    house style, whereas heading wording does not.
    """
    def table_is_parametric(cs):
        if any(UNIT_CELL.search(c) for c in cs):
            return True
        words = {m.group(0).lower() for m in LIMIT_WORDS.finditer(" ".join(cs))}
        return len(words) >= 2 and any(re.search(r"\d", c) for c in cs)

    # A table cell is a SINGLE line (`cells { row: 0 col: 1 text: "..." is_header: true }`)
    # while page prose is a `text_blocks {` block with its `text:` on its own line. Keying
    # on `cells {` therefore needs no brace-depth tracking, and cannot mistake page prose
    # for a table cell the way a naive in_table flag does.
    cells = []
    with open(path, errors="replace") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("cells {"):
                m = re.search(r'text:\s*"([^"]*)"', s)
                if m:
                    cells.append(m.group(1))
                continue
            if s.startswith("tables {"):
                if table_is_parametric(cells):
                    return True
                cells = []
                continue
            if "text:" in line and ELEC.search(line):
                return True
    return table_is_parametric(cells)


def kind_of(stem, pages, blocks):
    head = " ".join(blocks[:6]).lower()
    if stem.endswith("_BRIEF"):
        return "brief"
    if "product brief" in head:
        return "brief"
    if "catalog" in head or "pdf catalog" in head:
        return "catalog"
    if pages and int(pages) <= 3:
        return "short-form"
    return "datasheet"


def yq(s):
    """Quote a YAML scalar safely."""
    if s is None:
        return '""'
    s = str(s).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def load_sidecar(path):
    """A hand-curated sidecar keyed by pdf path (datasheets/sources.yaml, overrides.yaml).

    Both curated layers use one fixed, shallow shape, parsed without a YAML dependency so the
    generator keeps running under plain python3: a top-level map of `"<pdf>":` blocks, each with
    scalar `field: value` (or `field: [a, b, c]` list) entries at four-space indent. These fields
    are NOT in the doc-IR -- they record provenance (sources.yaml) or human corrections to
    heuristic fields (overrides.yaml) -- so they live beside the generated index and are merged
    here rather than mined. An absent record leaves the generator's own value / a documented default.
    """
    out, cur = {}, None
    if not os.path.exists(path):
        return out
    with open(path, errors="replace") as fh:
        for line in fh:
            raw = line.rstrip("\n")
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            m = re.match(r'^  "([^"]+)":\s*$', raw)          # `  "vendor/part/x.pdf":`
            if m:
                cur = m.group(1)
                out[cur] = {}
                continue
            m = re.match(r'^    (\w+):\s*(.*)$', raw)          # `    field: value` / `field: [a, b]`
            if m and cur is not None:
                k, raw_v = m.group(1), m.group(2).strip()
                if raw_v.startswith('"'):                       # quoted: keep content verbatim
                    q = re.match(r'"((?:[^"\\]|\\.)*)"', raw_v)
                    v = q.group(1) if q else raw_v.strip('"')
                else:                                           # strip a ` # ...` inline comment
                    raw_v = re.split(r"\s+#", raw_v, maxsplit=1)[0].rstrip()
                    if raw_v.startswith("[") and raw_v.endswith("]"):
                        v = [t.strip() for t in raw_v[1:-1].split(",") if t.strip()]
                    else:
                        v = raw_v.strip('"')
                out[cur][k] = v
    return out


def main(outpath):
    entries, byhash = [], {}
    for vendor in sorted(os.listdir(ROOT)):
        vp = os.path.join(ROOT, vendor)
        if not os.path.isdir(vp) or vendor.startswith("."):
            continue
        for part in sorted(os.listdir(vp)):
            pp = os.path.join(vp, part)
            if not os.path.isdir(pp):
                continue
            pdfs = sorted(f for f in os.listdir(pp) if f.lower().endswith(".pdf"))
            for pdf in pdfs:
                stem = pdf[:-4]
                ir = os.path.join(pp, stem + ".doc.textproto")
                e = dict(vendor=vendor, part=part, pdf=f"{vendor}/{part}/{pdf}",
                         stem=stem)
                if not os.path.exists(ir):
                    e.update(doc_ir=None, extracted=False)
                    entries.append(e)
                    continue
                md = top_meta(ir)
                pg = pages_text(ir)
                flat = [t for n in sorted(pg) for t in pg[n]]
                e.update(
                    doc_ir=f"{vendor}/{part}/{os.path.basename(ir)}",
                    extracted=True,
                    content_hash=md.get("content_hash"),
                    pages=md.get("page_count"),
                    doc_number=pick_docnum(flat, ir),
                    title=pick_title(flat, part),
                    covers=pick_covers(flat, part, ir),
                    kind=kind_of(stem, md.get("page_count"), flat),
                )
                e["variants"] = ordering_variants(ir, e["covers"])
                e["has_electrical"] = has_electrical(ir)
                pub, rev = pick_dates(flat)
                e.update(published=pub, revised=rev)
                byhash.setdefault(e["content_hash"], []).append(e["pdf"])
                entries.append(e)
    for e in entries:
        h = e.get("content_hash")
        e["duplicate_of"] = [p for p in byhash.get(h, []) if p != e["pdf"]] if h else []
    # Deterministic hygiene flag: the part dir claims a part the sheet never names.
    # Catches a dir named after an ordering variant (ti/TPS74615 -> sheet says
    # TPS746-Q1) and a dir named after a part that does not exist (ti/TPS12121).
    for e in entries:
        if not e.get("extracted"):
            continue
        want = re.sub(r"[^A-Z0-9]", "", e["part"].upper())
        e["dir_name_in_covers"] = any(
            want in re.sub(r"[^A-Z0-9]", "", c.upper()) or
            re.sub(r"[^A-Z0-9]", "", c.upper()) in want
            for c in e["covers"]) if e["covers"] else None
    json.dump(entries, open(outpath + ".json", "w"), indent=1)
    print(f"{len(entries)} documents; "
          f"{sum(1 for e in entries if not e['extracted'])} without doc-IR; "
          f"{sum(1 for e in entries if e.get('duplicate_of'))} duplicate files; "
          f"{sum(1 for e in entries if e.get('dir_name_in_covers') is False)} dir-name mismatches")
    return entries


HEADER = '''# datasheets/index.yaml -- index of the vendor datasheet corpus. ONE ENTRY PER DOCUMENT.
#
# WHY THIS FILE EXISTS. The folder layout is one dir per PART, but a datasheet almost
# always specifies a FAMILY: AD2426/AD2427/AD2428 share one sheet, TCAN1144/1145/1146
# share SLLSF80B. With nowhere to record that, the same document got filed twice
# (found: two byte-identical duplicate pairs) and family members were invisible.
#
# THE TWO LEVELS, AND WHY THEY ARE SEPARATE:
#   covers   -- part designations AS PRINTED on the sheet (AD2426, AD2427, AD2428).
#   variants -- ordering codes the sheet names (AD2428WCCSZ, AD2428BCPZ). A BOM
#               carries one of THESE.
# The PartSpec param join is an exact, case-insensitive MPN match with no suffix
# stripping and no package-code fuzzing (datasheet/param/set.go: "a near-miss MPN is
# a different part until a human says otherwise"). So a seed for a board part must be
# keyed on the ordering code, not the family name. Use this index to find WHICH SHEET
# to read; a PartSpec in projects/<customer>/params/ records what it says.
#
# GENERATED, with a hand-reviewed judgment layer. Deterministic fields (pdf, doc_ir,
# content_hash, pages, doc_number, published, revised, covers, variants) are mined
# from each <PART>.doc.textproto's first pages -- never from the PDF. `kind` and the
# curated `covers` involve judgment. Regenerate with genindex.py; do not hand-edit
# the deterministic fields, they will be overwritten.
#
# TWO CURATED SIDECARS are merged in (edit THOSE, never this generated file):
#   datasheets/sources.yaml   -- download PROVENANCE: source_url, access, download_method. Not in the
#     doc-IR (it records WHERE a file came from). access: public | public-mirror | gated | nda;
#     download_method: direct | js | playwright | none; missing record -> access/method: unknown.
#   datasheets/overrides.yaml -- CORRECTIONS to the heuristic judgment fields (title, published, kind,
#     has_electrical, covers) and dir_name_mismatch_ack, applied on top of the generator's guess so a
#     human fix persists instead of being reverted on the next run.
# Both key on the pdf path. See the /datasheet-download skill.
#
# CONFIDENTIALITY: this index holds part numbers and document metadata only, which are
# vendor-public facts. The PDFs and doc-IRs it points at are vendor-licensed and live in
# THIS repo (GM-InnerSource/datasheets), which is the internal boundary CONSTRAINTS C16
# means by "inside the deployment boundary". They are gitignored from the hw workspace
# and must never be committed to the shareable engine repo. Transcribed FACTS (a value
# plus its citation) may cross into projects/<customer>/params/; the documents may not.
'''


def emit_yaml(entries, path, generated):
    sources = load_sidecar(os.path.join(ROOT, "sources.yaml"))
    overrides = load_sidecar(os.path.join(ROOT, "overrides.yaml"))

    def acked(e):
        ov = overrides.get(e["pdf"], {})
        return str(ov.get("dir_name_mismatch_ack", "")).lower() in ("true", "1", "yes")

    L = []
    L.append(HEADER)
    L.append("version: 1")
    L.append(f"generated: {generated}")
    L.append('generator: "genindex.py (doc-IR pages 1-3 + full-text variant scan)"')
    vendors = sorted({e["vendor"] for e in entries})
    L.append(f"vendors: [{', '.join(vendors)}]")
    L.append("")
    dups = {}
    for e in entries:
        if e.get("duplicate_of"):
            dups.setdefault(e.get("content_hash"), []).append(e["pdf"])
    L.append("# --- documents ------------------------------------------------------------")
    L.append("documents:")
    for e in sorted(entries, key=lambda x: (x["vendor"], x["part"], x["stem"])):
        L.append(f"  - pdf: {yq(e['pdf'])}")
        L.append(f"    vendor: {e['vendor']}")
        L.append(f"    filed_under: {e['vendor']}/{e['part']}")
        if not e.get("extracted"):
            L.append("    extracted: false")
            L.append("    note: \"no doc-IR yet; run make pdf2doc-all\"")
            L.append("")
            continue
        L.append(f"    doc_ir: {yq(e['doc_ir'])}")
        L.append(f"    content_hash: {yq(e['content_hash'])}")
        # Judgment corrections merged from overrides.yaml, applied on top of the heuristic guess.
        ov = overrides.get(e["pdf"], {})
        L.append(f"    kind: {ov.get('kind', e['kind'])}")
        L.append(f"    pages: {e['pages']}")
        if e.get("doc_number"):
            L.append(f"    doc_number: {yq(e['doc_number'])}")
        published = ov.get("published", e.get("published"))
        if published:
            L.append(f"    published: {yq(published)}")
        if e.get("revised"):
            L.append(f"    revised: {yq(e['revised'])}")
        title = ov.get("title", e.get("title"))
        if title:
            L.append(f"    title: {yq(title)}")
        has_elec = ov.get("has_electrical", e.get("has_electrical", False))
        L.append(f"    has_electrical: {str(has_elec).lower()}"
                 f"   # false = no parameter table; cannot back a transcription")
        # Download provenance, merged from sources.yaml (not from the doc-IR). See load_sidecar.
        src = sources.get(e["pdf"], {})
        if src.get("url"):
            L.append(f"    source_url: {yq(src['url'])}")
        L.append(f"    access: {src.get('access', 'unknown')}")
        L.append(f"    download_method: {src.get('download_method', 'unknown')}")
        L.append(f"    covers: [{', '.join(ov.get('covers', e['covers']))}]")
        if e.get("variants"):
            L.append(f"    variants: [{', '.join(e['variants'][:24])}]")
        if e.get("duplicate_of"):
            L.append(f"    duplicate_of: [{', '.join(e['duplicate_of'])}]")
        if e.get("dir_name_in_covers") is False and not acked(e):
            L.append("    dir_name_mismatch: true   # dir is named for an ordering "
                     "variant or a non-existent part; see covers")
        elif e.get("dir_name_in_covers") is False and acked(e):
            L.append("    dir_name_mismatch_ack: true   # intentional: dir named for the "
                     "board part, not the sheet family (overrides.yaml)")
        L.append("")
    # Issues roll-up, so a reader sees the corpus's hygiene without diffing entries.
    L.append("# --- issues found by the generator ---------------------------------------")
    L.append("issues:")
    L.append("  duplicate_documents:")
    if dups:
        for h, paths in dups.items():
            L.append(f"    - content_hash: {yq(h)}")
            L.append(f"      filed_at: [{', '.join(paths)}]")
    else:
        L.append("    []")
    L.append("  dir_name_mismatches:   # acknowledged ones (overrides.yaml) are excluded")
    mm = [e for e in entries if e.get("dir_name_in_covers") is False and not acked(e)]
    if mm:
        for e in mm:
            covers = overrides.get(e["pdf"], {}).get("covers", e["covers"])
            L.append(f"    - {e['vendor']}/{e['part']}: "
                     f"[{', '.join(covers)}]")
    else:
        L.append("    []")
    L.append("  not_extracted:")
    ne = [e for e in entries if not e.get("extracted")]
    if ne:
        for e in ne:
            L.append(f"    - {e['pdf']}")
    else:
        L.append("    []")
    L.append("")
    open(path, "w").write("\n".join(L))
    print(f"wrote {path} ({len(entries)} documents)")


if __name__ == "__main__":
    ROOT = resolve_corpus_root(sys.argv[4] if len(sys.argv) > 4 else None)
    ents = main(sys.argv[1])
    if len(sys.argv) > 3:
        emit_yaml(ents, sys.argv[2], sys.argv[3])
