"""
Sanitization utilities for ChromaDB collection names and other identifiers.
"""

import re


def sanitize_collection_name(name: str) -> str:
    """
    ChromaDB 컬렉션 이름을 유효한 형식으로 변환.
    ChromaDB 규칙: [a-zA-Z0-9._-], 3~512자, 시작/끝은 [a-zA-Z0-9]

    예: 'Hippocampal Neurons' -> 'Hippocampal-Neurons'
        'My Collection!@#' -> 'My-Collection'
        '  test  ' -> 'test'
    """
    if not name or not name.strip():
        return 'unnamed-collection'

    sanitized = name.strip()
    sanitized = sanitized.replace(' ', '-')
    sanitized = re.sub(r'[^a-zA-Z0-9._-]', '', sanitized)
    sanitized = re.sub(r'[-]+', '-', sanitized)
    sanitized = re.sub(r'[.]+', '.', sanitized)
    sanitized = sanitized.strip('.-_')

    if len(sanitized) < 3:
        sanitized = sanitized + '-col'

    sanitized = sanitized[:512]
    sanitized = sanitized.rstrip('.-_')

    if not sanitized or len(sanitized) < 3:
        return 'unnamed-collection'

    return sanitized
