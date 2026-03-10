def format_result(obj) -> dict:
    """Convert a model instance to a plain dict."""
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}
