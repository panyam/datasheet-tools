"""Sweep the corpus for PIN-TO-PIN constraint prose, as candidates for a human to label.

A pin-to-pin constraint relates one terminal of a part to ANOTHER terminal of the
same part ("VDDA shall never exceed VDDAU by more than 0.5 V"). The parameter
contract has no shape for these; see agni#191, which this was built to supply
evidence for. Four forms are in question: ordering/tracking, mutual same-state,
common-net, and sequencing.

Deterministic inputs only: each <PART>.doc.textproto's text blocks. Never reads
the PDF, so every hit carries the page number a citation needs.

## The determinism boundary (same shape as datasheet-transcribe's)

- Deterministic: everything here. Same corpus in, same candidate list out.
- NOT deterministic, and NOT done here: deciding whether a candidate is really a
  constraint. This tool emits candidates with an auto-tag; a human labels them.
  Do not treat the NORM tag as a verdict.

## The three gates, and why each exists

1. ARITY. A pin-to-pin constraint names two or more terminals in one sentence.
   This is the cheapest and strongest filter, and it is why the matching is done
   per sentence rather than per text block.

2. MODALITY. This is the precision lever, not the idiom vocabulary. On the first
   pass roughly half the ordering hits were descriptions of device BEHAVIOUR that
   happen to compare two pins ("When VIN is higher than 6.2 V, the supply for LDO
   is VIN"). No comparison-verb list separates those from constraints; a modal
   verb does.

   A leading conditional is NOT part of this gate, though it was at first. Demoting
   on one cost 40 points of recall on ordering/tracking (60% against the hand
   labels, versus 100% without) to buy 4 points of precision, because the two it
   rejected were real constraints scoped by an operating REGIME rather than
   descriptions: "During power up, power down, and device operation, the voltage
   difference between AVCC and DVCC must not exceed ..." and "When a continuous
   3.3V supply is used ..., the VDDA supply pin must never exceed ...". A regime
   scope reads exactly like a behavioural conditional and means the opposite. The
   flag is still reported per row, so a labeller can see it; it just no longer
   demotes. Measured against the 44 hand-labelled rows in pinrelations.tsv:
   ordering/tracking 71% precision at 100% recall, common-net 17% at 100%.

   THOSE TWO NUMBERS PREDATE the split-subscript fix in TERMINAL below, which widened
   the candidate set, so they describe the old gate rather than this one. Re-measure
   once the newly surfaced rows are labelled. The recall figures deserve particular
   suspicion: they were computed against hand labels drawn from a candidate list that
   by construction could not contain what the arity gate was silently dropping, which
   makes a 100% recall claim circular.

3. OPERAND CLASS -- NOT IMPLEMENTED, and the next precision lever. Both operands
   have to be pins OF THE PART. Without this, 24 of 29 common-net hits were
   layout instructions ("The AGND and PGND pins must be connected to the ground
   planes using vias next to the bypass capacitors") or electrical-characteristics
   test conditions ("VIN1 shorted to VIN2 = VIN"). Neither is a pin relation, and
   the second is already modelled by the contract's `Condition`. Implementing this
   needs the part's own pin list, which is what agni#188 will produce.

## Label vocabulary (the `label` column of pinrelations.tsv)

    y   a requirement on the DESIGN that a netlist could be checked against
    n   not a pin-relation constraint: device behaviour, layout advice, or an
        electrical-characteristics test condition
    ?   a genuine pin-relation fact, but not something a design can violate
        (e.g. "VREFL and VSS_ANA are tied to VSS internally")

Usage:
    python3 tools/sweep_pin_relations.py            # report, grouped by form
    python3 tools/sweep_pin_relations.py --tsv      # one row per candidate, to label

    # re-label after a gate change WITHOUT losing the existing judgments:
    python3 tools/sweep_pin_relations.py --tsv --merge pinrelations.tsv > /tmp/new.tsv
    mv /tmp/new.tsv pinrelations.tsv
"""
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from genindex import resolve_corpus_root

ROOT = ""

# A terminal name as printed. Covers the V-prefixed supply/reference families with
# an optional parenthesised qualifier -- VCC(A) and VREF(B) are printed that way and
# a pattern without the parens splits them into two different terminals, which
# defeats the arity gate on exactly the documents that matter most.
#
# THE `\s*` AFTER THE LEADING V IS LOAD-BEARING, and its absence was a silent recall
# bug. A datasheet prints the subscript of VCCA smaller, and the PDF text layer
# emits that as "V CCA" with a space. The corpus is full of it: 509 "V CC", 98
# "V DD", 88 "V CCB", 58 "V CCA", ~850 occurrences in total. Without the `\s*` none
# of those is a terminal, so the ARITY gate -- described above as the cheapest and
# strongest filter -- silently saw one operand where the sentence had two, and
# dropped the sentence.
#
# The form it hid completely was mutual same-state. The TXB0104's own sentence, "The
# A and B sides of an unused data I/O pair must be held in the same state, that is,
# both at V CCI or both at GND", matches three same-state idioms and the modality
# gate, and was rejected for naming only GND. That produced a "zero hits across 62
# documents" reading which was an artifact of this pattern rather than a fact about
# the corpus. Re-measuring with the fix: ordering/tracking 14 -> 21 candidates,
# common-net 31 -> 35, mutual same-state 0 -> 1.
#
# The verdict on agni#191 survives the correction. Of the five newly-surfaced
# NORM-tagged candidates, four are the false-positive classes gate 3 exists for
# (device behaviour, a resistor bound, trivially-true wiring, layout advice) and the
# fifth is the TXB0104 instance already known. So mutual same-state still has one
# producer and common-net is still normative in one vendor's documents.
TERMINAL = re.compile(
    r"\b("
    r"[AVD]?V\s*(?:CC|DD|SS|IN|OUT|REF|BAT|BUS|IO|DDA|SSA|DDIO|PP|EE|LDO|SYS)"
    r"(?:\s*\([A-Za-z0-9]{1,4}\))?(?:[A-Z0-9]{0,3})"
    r"|GND|AGND|DGND|PGND|EPAD"
    r"|nRESET|RESET|nEN|EN|OE|nOE|CE|nCE|PDB|SHDN|nSHDN"
    r")\b"
)

# Constraint idioms, bucketed by the FORM the contract would have to carry.
FORMS = {
    "ordering/tracking": [
        r"less than or equal to", r"greater than or equal to",
        r"equal to or (?:less|greater)", r"must not exceed", r"never exceed",
        r"higher than", r"lower than",
        r"must (?:always )?be (?:greater|less|higher|lower)",
        r"within [^.]{0,20}(?:V|volt|mV)[^.]{0,20}of", r"maximum difference",
        r"difference between", r"track", r"must be (?:at|the) same voltage",
        r"cannot exceed", r"shall not exceed", r"\bexceed\b[^.]{0,30}by",
    ],
    "mutual same-state": [
        r"same state", r"held (?:in|at) the same", r"both at",
        r"same logic level", r"same level", r"tied to the same (?:state|level)",
    ],
    "common-net": [
        r"must be connected to", r"should be connected to",
        r"connected together", r"tied together", r"shorted together",
        r"connected to the same",
        r"tied to the same (?:net|node|supply|rail|potential)",
        r"must be (?:tied|shorted)", r"externally connected",
        r"internally connected to",
        r"\bshorted\b", r"\bshort\b[^.]{0,20}\bto\b",
        r"connect(?:ed|s)? [^.]{0,40} to (?:the )?same",
        r"\btie[ds]?\b[^.]{0,30}\bto\b",
        r"connected (?:directly )?to (?:the )?[A-Z]",
    ],
    "sequencing": [
        r"power(?:ed|ing)?[- ]up sequence", r"power[- ]up sequenc",
        r"supply sequenc", r"sequenc(?:ed|ing) ",
        r"before[^.]{0,40}(?:is|are) (?:applied|powered|stable|ramped)",
        r"until[^.]{0,40}(?:stable|settled|ramped|valid)",
        r"after[^.]{0,40}(?:has|have) (?:ramped|settled|stabilized|stabilised)",
        r"during power[- ]up", r"ramp(?:ed|s|ing)? (?:up )?(?:before|after)",
    ],
}
COMPILED = {k: [re.compile(p, re.I) for p in v] for k, v in FORMS.items()}

MODALITY = [
    ("must", re.compile(r"\bmust\b", re.I)),
    ("shall", re.compile(r"\bshall\b", re.I)),
    ("should", re.compile(r"\bshould\b", re.I)),
    ("required", re.compile(r"\b(?:require[sd]?|requirement)\b", re.I)),
    ("recommended", re.compile(r"\brecommend(?:ed|s)?\b", re.I)),
    ("never", re.compile(r"\bnever\b", re.I)),
]
# A leading conditional usually marks a behavioural clause rather than a constraint.
DESCRIPTIVE = re.compile(r"^\s*(?:when|if|during|while|in the event)\b", re.I)

# Boilerplate, not specification.
NOISE = re.compile(
    r"legal disclaimer|all rights reserved|trademark|terms and conditions"
    r"|no liability|export control|order now|technical documentation"
    r"|support (?:&|and) training|copyright",
    re.I,
)

TEXT_LINE = re.compile(r'^\s*text:\s*"(.*)"\s*$')
PAGE_LINE = re.compile(r"^\s*number:\s*(\d+)\s*$")


def sentences(text):
    # Datasheet prose is dense with "1.2 V." and "Fig. 9", so split conservatively:
    # only on a period that follows a word character and precedes a capital.
    parts = re.split(r"(?<=[a-z0-9\)\]])\.\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if p.strip()]


def unescape(s):
    return s.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", " ")


def modality(sent):
    found = [name for name, pat in MODALITY if pat.search(sent)]
    return "+".join(found) if found else "-none-"


def is_normative(sent):
    # Modality only. See the MODALITY note in the module docstring for why a
    # leading conditional is reported but does not demote.
    return modality(sent) != "-none-"


def leading_conditional(sent):
    return "cond" if DESCRIPTIVE.match(sent) else "-"


def scan(path):
    """Yield (page, form, sentence, terminals) for each candidate."""
    page = 0
    with open(path, errors="replace") as fh:
        for line in fh:
            m = PAGE_LINE.match(line)
            if m:
                page = int(m.group(1))
                continue
            m = TEXT_LINE.match(line)
            if not m:
                continue
            block = unescape(m.group(1))
            if NOISE.search(block):
                continue
            for sent in sentences(block):
                if len(sent) > 600:
                    continue
                # Internal whitespace is stripped so the split and unsplit spellings of one
                # terminal collapse to a single member. Without this the `\s*` fix would let a
                # sentence naming "VCCA" and "V CCA" -- the same pin, rendered both ways in one
                # document, which happens -- count as two operands and pass the arity gate on
                # its own. That would trade a recall bug for a precision one.
                terms = {re.sub(r"\s+", "", t).upper() for t in TERMINAL.findall(sent)}
                if len(terms) < 2:          # gate 1: arity
                    continue
                # Report EVERY form the sentence matches, not just the first. One
                # sentence can carry two ("VSS and VREFL should be shorted" plus a
                # 100 mV difference bound), and stopping at the first hid the
                # common-net evidence behind the ordering evidence.
                for form, pats in COMPILED.items():
                    if any(p.search(sent) for p in pats):
                        yield page, form, sent, sorted(terms)


def collect():
    hits = defaultdict(list)
    docs = 0
    for vendor in sorted(os.listdir(ROOT)):
        vdir = os.path.join(ROOT, vendor)
        if not os.path.isdir(vdir) or vendor.startswith((".", "tools")):
            continue
        for part in sorted(os.listdir(vdir)):
            pdir = os.path.join(vdir, part)
            if not os.path.isdir(pdir):
                continue
            for fn in sorted(os.listdir(pdir)):
                if not fn.endswith(".doc.textproto"):
                    continue
                docs += 1
                for page, form, sent, terms in scan(os.path.join(pdir, fn)):
                    hits[form].append((vendor, part, page, sent, terms))
    return docs, hits


def argvalue(flag):
    """The value following flag on the command line, or None."""
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def rowkey(form, vendor, part, page, sent):
    """Identity of a candidate ACROSS runs, for carrying a hand label forward.

    Deliberately excludes the `terminals` column, which is derived from the gates and
    therefore changes when they do -- the split-subscript fix rewrote it on rows whose
    sentence and judgment were untouched. The sentence, its document and its page are
    what a labeller actually judged.
    """
    return (form, vendor, part, str(page), sent)


def load_labels(path):
    """Map rowkey -> label from a previously labelled tsv. Empty when path is None.

    Rows whose label is blank are skipped rather than stored, so an unlabelled row in the
    prior file never masks a label a later run could supply.
    """
    if not path:
        return {}
    out = {}
    with open(path, errors="replace") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        cols = {name: i for i, name in enumerate(header)}
        need = ("label", "form", "vendor", "part", "page", "sentence")
        missing = [c for c in need if c not in cols]
        if missing:
            raise SystemExit(f"--merge file {path} lacks column(s): {', '.join(missing)}")
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if len(f) < len(header):
                continue
            label = f[cols["label"]].strip()
            if not label:
                continue
            k = rowkey(f[cols["form"]], f[cols["vendor"]], f[cols["part"]],
                       f[cols["page"]], f[cols["sentence"]])
            # One sentence can legitimately appear twice on a page (the same clause in two
            # text blocks), so a repeated key is not itself a problem. Two DIFFERENT
            # judgments for it are: the merge would pick one silently, and which one would
            # depend on file order. Say so rather than resolve it.
            if k in out and out[k] != label:
                print(f"warning: conflicting labels {out[k]!r} and {label!r} for "
                      f"{k[1]}/{k[2]} p{k[3]} ({k[0]}); keeping {out[k]!r}", file=sys.stderr)
                continue
            out[k] = label
    return out


def main():
    docs, hits = collect()
    tsv = "--tsv" in sys.argv

    if tsv:
        # One row per candidate, with an empty `label` column for a human. This is
        # the seed of a precision measurement; without labels the gates above are
        # asserted rather than measured.
        #
        # --merge <tsv> carries the labels of a PREVIOUS run forward onto the rows they
        # belong to. Without it, re-running after any gate change silently discards every
        # hand label, which is the expensive half of this file: the candidates regenerate
        # in seconds and the judgments do not. Redirect to a NEW file and swap, never
        # straight over the input.
        prior = load_labels(argvalue("--merge"))
        print("label\tform\tauto\tlead_cond\tmodality\tvendor\tpart\tpage"
              "\tterminals\tsentence")
        for form in FORMS:
            for vendor, part, page, sent, terms in hits[form]:
                sent = re.sub(r"\s+", " ", sent)
                auto = "NORM" if is_normative(sent) else "desc"
                label = prior.get(rowkey(form, vendor, part, page, sent), "")
                print(f"{label}\t{form}\t{auto}\t{leading_conditional(sent)}"
                      f"\t{modality(sent)}\t{vendor}\t{part}"
                      f"\t{page}\t{','.join(terms)}\t{sent}")
        return

    print(f"# corpus: {docs} documents under {ROOT}")
    print("# NORM/desc is an AUTO-TAG, not a verdict. Label by hand.")
    for form in FORMS:
        rows = hits[form]
        norm = [r for r in rows if is_normative(r[3])]
        print(f"\n{'=' * 78}\n## {form}")
        print(f"   all:       {len(rows):3d} sentences | "
              f"{len({f'{r[0]}/{r[1]}' for r in rows}):2d} parts | "
              f"{len({r[0] for r in rows})} vendors")
        print(f"   normative: {len(norm):3d} sentences | "
              f"{len({f'{r[0]}/{r[1]}' for r in norm}):2d} parts | "
              f"{len({r[0] for r in norm})} vendors: "
              f"{', '.join(sorted({r[0] for r in norm}))}\n")
        for vendor, part, page, sent, terms in rows:
            sent = re.sub(r"\s+", " ", sent)
            tag = "NORM" if is_normative(sent) else "desc"
            print(f"  [{tag}|{leading_conditional(sent)}|{modality(sent)}] "
                  f"[{vendor}/{part} p{page}] {sent}")
            print(f"      terminals: {', '.join(terms)}")


if __name__ == "__main__":
    ROOT = resolve_corpus_root()
    main()
