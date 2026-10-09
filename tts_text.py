"""Pure text splitting: preserve word order, keep phoneme ezafe groups together."""
import re


def sentence_pieces(text, max_chars=120):
    result = []
    for sentence in re.split(r'(?<=[.!؟!?؛])\s+|\n+', text.strip()):
        words = sentence.split()
        chunk = []
        for word in words:
            if chunk and len(' '.join(chunk + [word])) > max_chars:
                result.append((' '.join(chunk), 0.12))
                chunk = []
            chunk.append(word)
        if chunk:
            result.append((' '.join(chunk), 0.25))
    return result


def phoneme_pieces(text, token_count, budget=18):
    words = text.split()
    groups, group = [], []
    for word in words:
        group.append(word)
        if not word.endswith('1'):
            groups.append(' '.join(group))
            group = []
    if group:
        groups.append(' '.join(group))
    parts, current = [], ''
    for group in groups:
        clean = group.replace('1', '')
        if token_count(clean) > budget:
            # A very long ezafe chain must be split to respect the model budget.
            atoms = group.split()
        else:
            atoms = [group]
        for atom in atoms:
            candidate = (current + ' ' + atom).strip()
            if current and token_count(candidate.replace('1', '')) > budget:
                parts.append(current.replace('1', ''))
                current = ''
            if token_count(atom.replace('1', '')) > budget:
                raise ValueError('A single phoneme word exceeds the safe token budget')
            current = (current + ' ' + atom).strip()
    if current:
        parts.append(current.replace('1', ''))
    return parts
