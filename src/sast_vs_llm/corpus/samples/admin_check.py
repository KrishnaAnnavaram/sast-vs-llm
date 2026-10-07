def delete_account(user, account_id):
    """Delete an account. Only an administrator can do this."""
    assert user.get("is_admin"), "administrators only"
    return f"deleted {account_id}"
