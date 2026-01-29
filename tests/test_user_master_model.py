from werkzeug.security import generate_password_hash

from backend.models import UserMaster


def test_check_password_with_hash():
    um = UserMaster()
    um.password_hash = generate_password_hash("s3cret")

    assert um.check_password("s3cret") is True
    assert um.check_password("wrong") is False


def test_is_active_defaults_true_when_null():
    um = UserMaster()
    # _is_active defaults to None -> derived property should assume True
    assert um._is_active is None
    assert um.is_active is True

    # explicit False should be respected
    um._is_active = False
    assert um.is_active is False
