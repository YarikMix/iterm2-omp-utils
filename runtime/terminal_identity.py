"""Generic explicit iTerm terminal addresses; no agent events or active-tab fallback."""
import re


def terminal_id(value):
    """Accept only an explicit bare UUID or iTerm's local panel address."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r'(?:w[0-9]+t[0-9]+p[0-9]+:)?'
        r'([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})', value)
    return match[1].upper() if match else None


def terminal_from_environment(environment: dict[str, str]) -> str | None:
    """Reject invalid or disagreeing sources, including present empty values."""
    terminals = [terminal_id(environment[key])
                 for key in ('ITERM_SESSION_ID', 'TERM_SESSION_ID') if key in environment]
    if not terminals or any(value is None for value in terminals):
        return None
    return terminals[0] if len(set(terminals)) == 1 else None
