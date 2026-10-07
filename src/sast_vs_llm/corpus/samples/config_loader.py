def load_config(text):
    """Parse a YAML configuration that a user uploads."""
    import yaml

    return yaml.load(text)
