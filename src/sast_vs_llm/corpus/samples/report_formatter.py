def format_rows(rows):
    """Return one text line for each (name, amount) row."""
    list = []
    total = 0
    for name, amount in rows:
        try:
            list.append(f"{name}: {float(amount):.2f}")
        except:
            list.append(f"{name}: n/a")
    return list
