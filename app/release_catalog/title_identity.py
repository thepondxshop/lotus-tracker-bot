"""Narrow title comparison; no fuzzy similarity or distributor SKU rewriting."""
import re
from .extraction import norm

# Only an explicit parenthesized pack-count annotation is eligible for review.
# Edition years, language, case counts, collector variants and all other text stay.
PACK_NOTE = re.compile(r'\(\s*(\d{1,4})\s+packs?\s*\)',re.I)


def tokens(title):
    return tuple(re.findall(r'[^\W_]+',norm(title),re.UNICODE))


def title_relation(left,right):
    a,b=tokens(left),tokens(right)
    if not a or not b:
        return None
    if a==b:
        return 'TITLE_WORDS_EQUAL'
    ac,bc=PACK_NOTE.findall(left or ''),PACK_NOTE.findall(right or '')
    if (ac or bc) and tokens(PACK_NOTE.sub('',left or ''))==tokens(PACK_NOTE.sub('',right or '')):
        if len(ac)>1 or len(bc)>1:
            return 'PACK_COUNT_REVIEW'
        if ac and bc and int(ac[0])!=int(bc[0]):
            return 'PACK_COUNT_CONFLICT'
        return 'PACK_COUNT_REVIEW'
    return None
