"""Turn the FIPI namespace-prefixed markup into browser MathML."""
from __future__ import annotations


def normalize_fipi_mathml(soup) -> None:
    for node in soup.find_all(True):
        if node.name.startswith('m:'):
            node.name = node.name[2:]
        if node.name != 'mfenced':
            continue
        opening = str(node.attrs.pop('open', '('))
        closing = str(node.attrs.pop('close', ')'))
        separators = str(node.attrs.pop('separators', ',')) or ','
        children = [child for child in node.children if not isinstance(child, str) or child.strip()]
        node.name = 'mrow'
        open_tag = soup.new_tag('mo')
        open_tag.string = opening
        node.insert(0, open_tag)
        for index, child in enumerate(children[1:], 1):
            separator = soup.new_tag('mo')
            separator.string = separators[min(index - 1, len(separators) - 1)]
            child.insert_before(separator)
        close_tag = soup.new_tag('mo')
        close_tag.string = closing
        node.append(close_tag)
