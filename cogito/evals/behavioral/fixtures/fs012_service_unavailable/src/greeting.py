def health_status() -> str:
    return "ok"


def format_greeting(name: str) -> str:
    name = name.strip()
    return f"Hello, {name}!" if name else "Hello!"
