"""helpdocs - the FAQ and Resources tabs' text (folm_core/help/*.md).

Plain Markdown, easy to edit: '# Category', then '## Topic' and its text. The window shows the
categories as branches that open into their topics.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def read(name):
    """folm_core/help/<name>.md -> [(category, [(title, markdown)])]. '# ' starts a category,
    '## ' a topic; everything under a topic is its text."""
    cats = []
    try:
        with open(os.path.join(HERE, "help", name + ".md"), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return cats
    body = None
    for line in lines:
        if line.startswith("# "):
            cats.append((line[2:].strip(), []))
            body = None
        elif line.startswith("## ") and cats:
            body = []
            cats[-1][1].append((line[3:].strip(), body))
        elif body is not None:
            body.append(line)
    return [(c, [(t, "\n".join(b).strip()) for t, b in topics]) for c, topics in cats]
