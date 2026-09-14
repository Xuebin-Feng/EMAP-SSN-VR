import os
import re
import fnmatch
import numpy as np
from collections import Counter
import Settings as cfg
import Viewer_Utils as utils
import Command_Engine
from utilities.Sequence_Utils import (
    DISPLAYED_POSITION_ATOM_PATTERN,
    normalize_displayed_position_atom,
    reject_bare_negative_positions,
)


_QUERY_POSITION_ENDPOINT_PATTERN = (
    rf"(?:{DISPLAYED_POSITION_ATOM_PATTERN}|E(?:ND)?)"
)
_QUERY_POSITION_RANGE_RE = re.compile(
    rf"^({_QUERY_POSITION_ENDPOINT_PATTERN})\s*-\s*"
    rf"({_QUERY_POSITION_ENDPOINT_PATTERN})$",
    re.IGNORECASE,
)
_FREQUENCY_TARGET_PATTERN = r"(?:\([A-Za-z]*\)|[A-Za-z_]+)"
_FREQUENCY_VALUE_PATTERN = r"\d+(?:\.\d+)?%?"
_PARENTHESIZED_FREQUENCY_CONDITION_RE = re.compile(
    rf"\(\s*({_FREQUENCY_TARGET_PATTERN})\s*(>=|<=|>|<)\s*"
    rf"({_FREQUENCY_VALUE_PATTERN})\s*\)"
)
_SINGLE_FREQUENCY_CONDITION_RE = re.compile(
    rf"\s*({_FREQUENCY_TARGET_PATTERN})\s*(>=|<=|>|<)\s*"
    rf"({_FREQUENCY_VALUE_PATTERN})\s*"
)
_FREQUENCY_PARENTHESES_MESSAGE = (
    "Error: Individual frequency arguments in multi-condition queries must be "
    "enclosed in parentheses '()'.\n"
    "Example: [K>10%], [(K>0.1) & (R>0.05)], "
    "[((RHK)>50%) & ((DE)>20%)]"
)


class _FrequencyParenthesesError(ValueError):
    """Raised when a compound frequency comparison lacks its outer parentheses."""


class _FrequencyLogicParser:
    """Evaluate mask atoms with the shared Boolean-operator precedence."""

    def __init__(self, text, masks):
        self.text = text
        self.masks = masks
        self.position = 0

    def _skip_space(self):
        while self.position < len(self.text) and self.text[self.position].isspace():
            self.position += 1

    def _error(self):
        raise ValueError(
            "Invalid frequency Boolean expression. Ensure operators and "
            "parentheses are complete."
        )

    def parse(self):
        self._skip_space()
        if self.position >= len(self.text):
            self._error()
        result = self._parse_or()
        self._skip_space()
        if self.position != len(self.text):
            self._error()
        return result

    def _parse_or(self):
        result = self._parse_xor()
        while True:
            self._skip_space()
            if self.position >= len(self.text) or self.text[self.position] != "|":
                return result
            self.position += 1
            result = result | self._parse_xor()

    def _parse_xor(self):
        result = self._parse_and()
        while True:
            self._skip_space()
            if self.position >= len(self.text) or self.text[self.position] != "^":
                return result
            self.position += 1
            result = result ^ self._parse_and()

    def _parse_and(self):
        result = self._parse_unary()
        while True:
            self._skip_space()
            if self.position >= len(self.text) or self.text[self.position] != "&":
                return result
            self.position += 1
            result = result & self._parse_unary()

    def _parse_unary(self):
        self._skip_space()
        if self.position < len(self.text) and self.text[self.position] == "!":
            self.position += 1
            return ~self._parse_unary()
        return self._parse_primary()

    def _parse_primary(self):
        self._skip_space()
        if self.position >= len(self.text):
            self._error()
        if self.text[self.position] == "(":
            self.position += 1
            result = self._parse_or()
            self._skip_space()
            if self.position >= len(self.text) or self.text[self.position] != ")":
                self._error()
            self.position += 1
            return result

        match = re.match(r"M_\d+", self.text[self.position:])
        if not match:
            self._error()
        key = match.group(0)
        self.position += len(key)
        try:
            return self.masks[key]
        except KeyError:
            self._error()


def _normalize_frequency_target(target_raw):
    target = target_raw.strip().upper()
    if target.startswith('(') and target.endswith(')'):
        target_aas = target[1:-1]
        if len(target_aas) < 2:
            raise ValueError(
                f"Grouped amino-acid target '{target}' must contain at least two "
                "one-letter residue symbols."
            )
        return tuple(dict.fromkeys(target_aas))
    return target


def _parse_frequency_threshold(value_text):
    value_clean = value_text.strip()
    if value_clean.endswith('%'):
        return float(value_clean[:-1]) / 100.0
    value = float(value_clean)
    return value if value <= 1.0 else (value / 100.0)


def _evaluate_frequency_condition(
    target_raw,
    operator,
    value_text,
    gap_fractions,
    aa_fractions,
):
    target = _normalize_frequency_target(target_raw)
    threshold = _parse_frequency_threshold(value_text)

    if isinstance(target, tuple):
        column_frequencies = np.zeros_like(gap_fractions, dtype=float)
        for target_aa in target:
            column_frequencies += aa_fractions.get(
                target_aa,
                np.zeros_like(gap_fractions, dtype=float),
            )
    elif target in {'_', 'GAP'}:
        column_frequencies = gap_fractions
    else:
        column_frequencies = aa_fractions.get(
            target,
            np.zeros_like(gap_fractions, dtype=float),
        )

    comparisons = {
        '>': np.greater,
        '<': np.less,
        '>=': np.greater_equal,
        '<=': np.less_equal,
    }
    return comparisons[operator](column_frequencies, threshold)


def evaluate_frequency_logic(inner, gap_fractions, aa_fractions):
    """Evaluate query frequency logic against precomputed per-column fractions."""
    masks = {}
    mask_idx = 0

    def condition_repl(match):
        nonlocal mask_idx
        target_raw, operator, value_text = match.groups()
        mask_key = f"M_{mask_idx}"
        masks[mask_key] = _evaluate_frequency_condition(
            target_raw,
            operator,
            value_text,
            gap_fractions,
            aa_fractions,
        )
        mask_idx += 1
        return mask_key

    expression = _PARENTHESIZED_FREQUENCY_CONDITION_RE.sub(
        condition_repl,
        inner,
    )
    if mask_idx == 0:
        single_match = _SINGLE_FREQUENCY_CONDITION_RE.fullmatch(inner)
        if single_match:
            expression = condition_repl(single_match)

    if re.search(r'[><]', expression) or mask_idx == 0:
        raise _FrequencyParenthesesError(_FREQUENCY_PARENTHESES_MESSAGE)

    result = _FrequencyLogicParser(expression, masks).parse()

    result_mask = np.asarray(result, dtype=bool)
    expected_shape = np.asarray(gap_fractions).shape
    if result_mask.shape != expected_shape:
        raise ValueError(
            "Frequency logic did not resolve to one value per alignment position."
        )
    return result_mask


def parse_query_positions(position_spec, valid_labels):
    """Expand a query position list against mapped alignment labels."""
    text = str(position_spec).strip()
    if text.startswith('[') and text.endswith(']'):
        text = text[1:-1]

    reject_bare_negative_positions(text)

    parsed_args = [part.strip() for part in text.split(',') if part.strip()]
    expanded_positions = []
    max_val = valid_labels[-1][0] if valid_labels else (0, 0)

    def parse_to_tuple(value):
        normalized = normalize_displayed_position_atom(value, allow_end=True)
        if normalized in {"E", "END"}:
            return max_val
        major_text, separator, insertion_text = normalized.partition('.')
        return int(major_text), int(insertion_text) if separator else 0

    for part in parsed_args:
        range_match = _QUERY_POSITION_RANGE_RE.fullmatch(part)
        if range_match:
            start_value, end_value = sorted(
                [parse_to_tuple(range_match.group(1)), parse_to_tuple(range_match.group(2))]
            )
            for value, label in valid_labels:
                if start_value <= value <= end_value and label not in expanded_positions:
                    expanded_positions.append(label)
            continue

        normalized = normalize_displayed_position_atom(part, allow_end=True)
        if normalized in {"E", "END"} and valid_labels:
            normalized = valid_labels[-1][1]
        if normalized not in expanded_positions:
            expanded_positions.append(normalized)

    return expanded_positions


def print_help():
    print("""
    Subsection Query & Alignment Statistics Tool
    ==========================================
    Usage: query [EXPRESSION] [POSITIONS]
           query [EXPRESSION] [LOGIC_ARGUMENT]
           query help

    Description:
      Queries the loaded alignment for the amino acid distribution at the specified
      reference positions (Mode 1), OR searches for alignment positions matching
      specific amino acid frequency criteria (Mode 2).

      Can query globally OR on a subset of nodes using logic.

      * QUICK USE: If no expression is provided, the command automatically targets
        the nodes currently selected in the viewer. If no nodes are selected, it
        defaults to querying ALL nodes in the entire network.
      * Every report is printed to this terminal; there is no viewer console here.

    Syntax Modes:
      1. Position Breakdown Mode:
         [POSITIONS] - Comma-separated list or ranges enclosed in brackets.
         Accepts decimal (insertion) positions, and 'E' or 'END' for the last
         mapped position. Negative positions (produced by 'offset') must be
         enclosed individually in parentheses.
         Example: [(-1), 0, 15.1, 20-30, 250-E, END] or [(-3)-(-1)]

      2. Position Frequency Search Mode:
         [LOGIC_ARGUMENT] - Frequency criteria with operators (>, <, >=, <=) and
         logical operators (&, |, !, ^). Single arguments do NOT require ().
         Multi-condition queries MUST enclose each individual argument in ().
         Spaces are allowed. Accepts percentages (e.g. 10%) or decimals (e.g. 0.1).
         Accepts residue codes (A-Z) and 'GAP' or '_' for gaps (case-insensitive).
         Parenthesized residue sets sum their frequencies, e.g. [(RHK)>50%].
         Frequencies divide by all mapped sequences in the selected subset, so gaps
         reduce residue percentages.

    Sequence Selection Expression Targets (Do NOT use spaces inside expressions!):
      1. AA Position:  [AA][Pos] (e.g., P106, _100)
      2. Header Text:  "[Text]"  (e.g., "3HMU", "*4A6T*")
      3. File Search:  @[File]@  (e.g., @my_list@, @my_seqs.fasta@)
      4. NCBI List:    @[NCBI][File]@ (Extracts & matches NCBI IDs from file and headers)
      5. Labels:       #[Name]#  (e.g., #cluster_1#, #noise#, #my_group#)
      6. UI Selection: $sele$    (Targets nodes currently selected in viewer)
      7. Metadata:     {Key Op Val} (e.g., {Length>500}, {Organism=*coli*})

    Logic Operators:
      & (AND), | (OR), ! (NOT), ^ (XOR)

    Examples:
      query [10, 15, 20-30]                    (Queries pos 10, 15, and 20 to 30)
      query [250-E]                            (Queries pos 250 to the last mapped position)
      query P106 [150-160]                     (Sub-query pos 150-160 ONLY for nodes with Pro at 106)
      query "ATA"&#kinase# [45-50]             (Sub-query pos 45-50 for nodes with "ATA" AND in #kinase#)
      query {Length>500} [10-20]               (Sub-query pos 10-20 for nodes with Length > 500)
      query [K>10%]                            (Finds positions where Lysine > 10%)
      query [(RHK)>50%]                        (Finds positions where R+H+K > 50%)
      query [(K>0.1) & (R>0.05)]               (Finds positions where K > 10% and R > 5%)
      query {Length>500} [!(GAP>30%) & (K>5%)] (Low-gap, Lys-rich positions in length>500)
    """)

def run(viewer, args):
    if not args or args[0].lower() in ['help', '-h', '--help']:
        print_help()
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "Help information printed to the console."
        return

    # viewer.alignment is None whenever Alignment_Manager construction failed;
    # the old 'viewer.alignment.aln' test raised AttributeError instead.
    alignment = getattr(viewer, 'alignment', None)
    if alignment is None or alignment.aln is None:
        msg = "Error: No alignment loaded in the viewer."
        Command_Engine.print_help(viewer, msg)
        return

    if len(alignment.aln) == 0:
        msg = ("Error: The loaded MSA contains no aligned rows for the current network. "
               "Query analysis is unavailable.")
        Command_Engine.print_help(viewer, msg)
        return

    # --- Reconstruct bracketed arguments (in case of spaces within brackets) ---
    reconstructed_args = []
    temp_bracket = []
    in_bracket = False

    for a in args:
        if '[' in a and not in_bracket:
            if a.count('[') > a.count(']'):
                in_bracket = True
                temp_bracket.append(a)
            else:
                reconstructed_args.append(a)
        elif in_bracket:
            temp_bracket.append(a)
            if ']' in a:
                joined = " ".join(temp_bracket)
                if joined.count('[') <= joined.count(']'):
                    reconstructed_args.append(joined)
                    temp_bracket = []
                    in_bracket = False
        else:
            reconstructed_args.append(a)

    if temp_bracket:
        reconstructed_args.extend(temp_bracket)
    args = reconstructed_args

    # --- 1. Extract Positions/Logic Argument (First argument containing brackets) ---
    bracket_indices = [i for i, a in enumerate(args) if a.strip().startswith('[') and a.strip().endswith(']')]

    if not bracket_indices:
        msg = "Error: No bracketed argument provided. Use [...] syntax (e.g., [10-20] or [K>10%])."
        Command_Engine.print_help(viewer, msg)
        return

    pos_idx = bracket_indices[0]
    pos_str = args.pop(pos_idx).strip()

    # --- 2. Isolate Expression & Apply Smart Fallbacks ---
    expr = "$sele$"
    if len(args) > 0:
        expr = "".join(args) # Join remaining to reconstruct expression without spaces

    # Smart Fallback to ALL Nodes
    if expr == "$sele$" and not getattr(viewer, 'selected_indices', []):
        expr = '"*"'  # The wildcard string matches all headers
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = "No selection found. Defaulting to ALL nodes."
        print("No nodes selected. Defaulting to ALL nodes in the network.")

    # --- 3. Compute Subset Rows ---
    target_rows = None
    n_seqs = len(viewer.alignment.aln)
    subset_mode = False

    if expr:
        # $sele$ used to be written out to Header_Lists/_sele.txt and read back as
        # @_sele.txt@, which wrote into the user's shared list directory on every
        # query. Command_Engine resolves it from the live selection mask instead.
        viewer_to_aln, valid_indices = Command_Engine.get_alignment_mapping(viewer)

        expr = re.sub(r'\{([^}]+)\}', lambda m: '{' + m.group(1).replace(' ', '') + '}', expr)
        try:
            mask = Command_Engine.parse_advanced_expression(expr, viewer_to_aln, valid_indices, viewer.full_headers, getattr(viewer, 'cluster_labels', None), getattr(viewer, 'group_labels', None), getattr(viewer, 'alignment', None), metadata=getattr(viewer, 'metadata', None), selection_mask=Command_Engine.get_selected_mask(viewer))
        except Exception as e:
            Command_Engine.report_selection_error(viewer, expr, e, "Query")
            return

        valid_nodes = np.where(mask)[0]
        aln_rows = viewer_to_aln[valid_nodes]
        target_rows = aln_rows[aln_rows != -1]

        n_seqs = len(target_rows)
        subset_mode = True

        if n_seqs == 0:
            msg = f"No sequences matched the expression '{expr}'. Aborting query."
            viewer.console_text.text = msg
            print("-" * 50)
            print(msg)
            print("-" * 50)
            return

    # --- 4. Detect Mode: Position Breakdown (Mode 1) vs Frequency Search (Mode 2) ---
    inner = pos_str[1:-1].strip()
    is_logic_mode = bool(re.search(r'[><]', inner))

    # Provenance: the terminal is the only surface, so every report says which
    # alignment, reference and offset produced the numbers below it.
    msa_file = getattr(viewer.alignment, 'msa_file', None) or getattr(cfg, 'MSA_FILE', 'None')
    if isinstance(msa_file, str) and msa_file:
        msa_file_display = os.path.basename(msa_file)
    else:
        msa_file_display = str(msa_file)

    resolved_ref = getattr(viewer.alignment, 'resolved_ref_full', None)
    if resolved_ref and str(resolved_ref).strip().lower() != 'none':
        ref_display = resolved_ref
        offset_display = str(int(getattr(viewer.alignment, 'offset', 0) or 0))
    else:
        ref_display = "None (Unanchored)"
        offset_display = f"{int(getattr(viewer.alignment, 'offset', 0) or 0)} (inactive)"

    is_sparse = hasattr(viewer.alignment.aln, 'matrix')

    # Get mapped position labels in order
    label_to_col = getattr(viewer.alignment, 'label_to_col', None) or {}
    valid_labels = []
    for lbl in label_to_col.keys():
        try:
            parts = str(lbl).split('.')
            major = int(parts[0])
            minor = int(parts[1]) if len(parts) > 1 else 0
            valid_labels.append(((major, minor), lbl))
        except ValueError:
            pass
    valid_labels.sort(key=lambda x: x[0])
    ordered_pos_labels = [lbl for _, lbl in valid_labels]

    if is_logic_mode:
        # =====================================================================
        # MODE 2: POSITION FREQUENCY SEARCH MODE
        # =====================================================================
        print("-" * 50)
        if subset_mode:
            print(f"QUERY POSITION SEARCH SUBSET: '{expr}' ({n_seqs} sequences mapped)")
        else:
            print(f"QUERY POSITION SEARCH GLOBAL: All Mapped Alignment Sequences ({n_seqs} sequences)")
        print(f"Alignment File:   {msa_file_display}")
        print(f"Active Reference: {ref_display}")
        print(f"Alignment Offset: {offset_display}")
        print(f"Search Criteria:  [{inner}]")
        print("-" * 50)

        n_cols = len(ordered_pos_labels)
        if n_cols == 0:
            print("No valid alignment columns mapped.")
            print("-" * 50)
            if hasattr(viewer, 'console_text'):
                viewer.console_text.text = "No valid alignment columns mapped."
            return

        # Precompute AA and Gap frequencies for all mapped columns
        all_gap_fracs = np.zeros(n_cols, dtype=float)
        all_aa_fracs = {} # aa_char -> 1D numpy array of length n_cols

        for idx, pos_label in enumerate(ordered_pos_labels):
            col_idx = label_to_col[pos_label]
            if is_sparse:
                if subset_mode:
                    sliced = viewer.alignment.aln.matrix[target_rows, col_idx]
                    if hasattr(sliced, 'toarray'):
                        dense_col = sliced.toarray().flatten()
                    else:
                        dense_col = np.array(sliced).flatten()
                    n_gaps = np.sum(dense_col == 0)
                    residues = dense_col[dense_col != 0]
                    counts = Counter(residues)
                else:
                    col_vec = viewer.alignment.aln.matrix[:, col_idx]
                    residues = col_vec.data
                    n_gaps = n_seqs - len(residues)
                    counts = Counter(residues)

                all_gap_fracs[idx] = n_gaps / n_seqs if n_seqs > 0 else 0.0

                for aa_int, count in counts.items():
                    aa_char = viewer.alignment.aln.int_to_aa.get(aa_int, 'X').upper()
                    if aa_char not in all_aa_fracs:
                        all_aa_fracs[aa_char] = np.zeros(n_cols, dtype=float)
                    all_aa_fracs[aa_char][idx] += (count / n_seqs) if n_seqs > 0 else 0.0
            else:
                if subset_mode:
                    col_chars = [viewer.alignment.aln[row].seq[col_idx].upper() for row in target_rows]
                else:
                    col_chars = [rec.seq[col_idx].upper() for rec in viewer.alignment.aln]

                raw_counts = Counter(col_chars)
                n_gaps = sum(raw_counts[g] for g in cfg.GAP_CHARS if g in raw_counts)
                all_gap_fracs[idx] = n_gaps / n_seqs if n_seqs > 0 else 0.0

                for aa_char, count in raw_counts.items():
                    if aa_char not in cfg.GAP_CHARS:
                        aa_clean = aa_char.upper()
                        if aa_clean not in all_aa_fracs:
                            all_aa_fracs[aa_clean] = np.zeros(n_cols, dtype=float)
                        all_aa_fracs[aa_clean][idx] += (count / n_seqs) if n_seqs > 0 else 0.0

        try:
            pos_mask = evaluate_frequency_logic(inner, all_gap_fracs, all_aa_fracs)
        except _FrequencyParenthesesError as error:
            if hasattr(viewer, 'console_text'):
                viewer.console_text.text = "Error: Individual frequency arguments must be enclosed in ()"
            print("-" * 50)
            print(str(error))
            print("-" * 50)
            return
        except ValueError as error:
            msg = f"Error parsing position logic '[{inner}]': {error}"
            if hasattr(viewer, 'console_text'):
                viewer.console_text.text = msg
            print(msg)
            print("-" * 50)
            return

        matching_indices = np.where(pos_mask)[0]
        matching_labels = [ordered_pos_labels[i] for i in matching_indices]

        print(f"Matching Positions ({len(matching_labels)} found):")
        if matching_labels:
            print(", ".join(str(lbl) for lbl in matching_labels))
            print("-" * 50)

            for idx in matching_indices:
                pos_label = ordered_pos_labels[idx]
                gap_pct = all_gap_fracs[idx] * 100.0

                valid_aas = []
                for aa_char, fracs in all_aa_fracs.items():
                    pct = fracs[idx] * 100.0
                    if pct >= 1.0:
                        valid_aas.append((aa_char, pct))
                valid_aas.sort(key=lambda x: x[1], reverse=True)

                out_str = f"Pos {pos_label:<8}\tGap {gap_pct:>5.1f}%"
                for aa, pct in valid_aas:
                    out_str += f" | {aa} {pct:>5.1f}%"
                print(out_str)
        else:
            print("[No positions matched the search criteria]")

        print("-" * 50)
        if hasattr(viewer, 'console_text'):
            viewer.console_text.text = f"Found {len(matching_labels)} matching position(s)."
        return

    # =========================================================================
    # MODE 1: POSITION BREAKDOWN MODE
    # =========================================================================
    found_count = 0

    print("-" * 50)
    if subset_mode:
        print(f"QUERY SUBSET: '{expr}' ({n_seqs} sequences mapped)")
    else:
        print(f"QUERY GLOBAL: All Mapped Alignment Sequences ({n_seqs} sequences)")
    print(f"Alignment File:   {msa_file_display}")
    print(f"Active Reference: {ref_display}")
    print(f"Alignment Offset: {offset_display}")
    print("-" * 50)

    try:
        expanded_positions = parse_query_positions(inner, valid_labels)
    except ValueError as exc:
        Command_Engine.print_help(viewer, f"Error: {exc}")
        return

    # --- 5. Query the Matrix ---
    for pos in expanded_positions:
        if pos not in label_to_col:
            print(f"Pos {pos: >5}: [Not found in active alignment mapping]")
            continue

        col_idx = label_to_col[pos]
        found_count += 1

        if is_sparse:
            if subset_mode:
                # Slicing specific rows returns a dense matrix or array
                sliced = viewer.alignment.aln.matrix[target_rows, col_idx]
                if hasattr(sliced, 'toarray'):
                    dense_col = sliced.toarray().flatten()
                else:
                    dense_col = np.array(sliced).flatten()

                n_gaps = np.sum(dense_col == 0)
                residues = dense_col[dense_col != 0]
                counts = Counter(residues)
            else:
                col_vec = viewer.alignment.aln.matrix[:, col_idx]
                residues = col_vec.data
                n_gaps = n_seqs - len(residues)
                counts = Counter(residues)

            aa_counts = {}
            for aa_int, count in counts.items():
                aa_char = viewer.alignment.aln.int_to_aa.get(aa_int, 'X')
                aa_counts[aa_char] = aa_counts.get(aa_char, 0) + count
        else:
            if subset_mode:
                col_chars = [viewer.alignment.aln[row].seq[col_idx].upper() for row in target_rows]
            else:
                col_chars = [rec.seq[col_idx].upper() for rec in viewer.alignment.aln]

            raw_counts = Counter(col_chars)
            n_gaps = sum(raw_counts[g] for g in cfg.GAP_CHARS if g in raw_counts)
            aa_counts = {aa: count for aa, count in raw_counts.items() if aa not in cfg.GAP_CHARS}

        # Gap-Diluted Calculation
        gap_pct = (n_gaps / n_seqs) * 100.0 if n_seqs > 0 else 0.0

        valid_aas = []
        for aa, count in aa_counts.items():
            pct = (count / n_seqs) * 100.0 if n_seqs > 0 else 0.0
            if pct >= 1.0:
                valid_aas.append((aa, pct))

        valid_aas.sort(key=lambda x: x[1], reverse=True)

        out_str = f"Pos {pos:<8}\tGap {gap_pct:>5.1f}%"
        for aa, pct in valid_aas:
            out_str += f" | {aa} {pct:>5.1f}%"

        print(out_str)

    print("-" * 50)

    if found_count > 0:
        Command_Engine.print_help(viewer, f"Queried {found_count} position(s).")
    else:
        Command_Engine.print_help(
            viewer,
            "No valid positions queried: none of the requested positions exist in "
            "the active alignment mapping.")
