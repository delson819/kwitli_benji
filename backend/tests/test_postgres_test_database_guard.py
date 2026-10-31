import pytest

from conftest import _postgres_server_ip


@pytest.mark.parametrize(
    ("address", "is_loopback"),
    [
        ("127.0.0.1/32", True),
        ("::1/128", True),
        ("172.18.0.2/16", False),
        ("8.8.8.8/32", False),
    ],
)
def test_postgres_effective_inet_address_is_checked_as_an_ip(address, is_loopback):
    assert _postgres_server_ip(address).is_loopback is is_loopback


def test_invalid_postgres_effective_address_is_rejected():
    with pytest.raises(ValueError):
        _postgres_server_ip("not-an-ip/32")
