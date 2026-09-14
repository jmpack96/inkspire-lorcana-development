import pytest

from lorcana.duels.credentials import DuelsCredentialError, EnvironmentCredentialResolver


def test_environment_credential_resolver():
    resolver = EnvironmentCredentialResolver({"DUELS_TOKEN": " abc "})
    assert resolver.resolve("env:DUELS_TOKEN") == "abc"


def test_environment_credential_resolver_never_accepts_inline_secret_scheme():
    resolver = EnvironmentCredentialResolver({})
    with pytest.raises(DuelsCredentialError, match="env:"):
        resolver.resolve("token:secret")
