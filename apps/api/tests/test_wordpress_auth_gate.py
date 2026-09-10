import hashlib
import hmac
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from core.models import Role, User, UserRole
from core.wordpress_auth import request_class, wordpress_auth_gate

pytestmark = pytest.mark.django_db
PROOF = 'edge-fixture-' * 8
KEY = 'wordpress-fixture-' * 8


@pytest.fixture
def configured(settings):
    settings.KAIROS_PROXY_TOKEN = PROOF
    settings.KAIROS_WORDPRESS_GATE_KEY = KEY


def principal(role='administrador'):
    user = User.objects.create_user(username=role, password='isolated-password', mfa_enabled=True, mfa_secret_encrypted='encrypted-fixture')
    UserRole.objects.create(user=user, role=Role.objects.get(slug=role))
    return user


def gate(user=None, method='GET', uri='/wp-admin/', **headers):
    request = RequestFactory().get('/api/internal/wordpress-auth', HTTP_X_KAIROS_PROXY=PROOF,
                                   HTTP_X_FORWARDED_METHOD=method, HTTP_X_FORWARDED_URI=uri, **headers)
    request.user = user or AnonymousUser()
    request.session = {'mfa_verified': True, 'user_session_version': user.session_version if user else 0}
    return request


@pytest.mark.parametrize('method,uri', [('GET', '/'), ('HEAD', '/blog/artigo/'), ('GET', '/wp-json/wp/v2/posts'), ('GET', '/?rest_route=/wp/v2/posts')])
def test_public_read_preserved(configured, method, uri):
    response = wordpress_auth_gate(gate(method=method, uri=uri))
    assert response.status_code == 204
    assert '.public.' in response['X-Kairos-Wp-Gate']
    assert response['Cache-Control'] == 'private, no-store'


@pytest.mark.parametrize('method,uri', [('POST', '/wp-login.php'), ('GET', '/wp-login.php'), ('GET', '/wp-admin/'),
    ('GET', '/wp-admin'), ('GET', '/%2577p-admin/'), ('GET', '/wp-cron.php'), ('GET', '/wp-content/plugins/example/action.php'),
    ('POST', '/wp-json/wp/v2/posts'), ('DELETE', '/?rest_route=/wp/v2/posts/1'), ('GET', '/?_method=DELETE'),
    ('GET', '/wp-json/wp/v2/posts?context=edit'), ('GET', '/?preview=true')])
def test_anonymous_cannot_use_wordpress_auth_paths(configured, method, uri):
    response = wordpress_auth_gate(gate(method=method, uri=uri))
    assert response.status_code == 403
    assert 'X-Kairos-Wp-Gate' not in response


@pytest.mark.parametrize('uri', ['/xmlrpc.php', '/XMLRPC.php/test', '/%78mlrpc.php', '//foreign/a', '/%00', '/%5cwp-admin', '/#fragment'])
def test_denied_even_with_administrator(configured, uri):
    assert wordpress_auth_gate(gate(principal(), uri=uri)).status_code == 403


@pytest.mark.parametrize('role', ['aluno', 'editor', 'suporte', 'revisor-juridico', 'conta-de-servico'])
def test_non_administrative_roles_cannot_pass(configured, role):
    assert wordpress_auth_gate(gate(principal(role))).status_code == 403


@pytest.mark.parametrize('change', ['disabled', 'no_secret', 'no_mfa', 'session', 'inactive', 'service'])
def test_actual_current_mfa_and_role_required(configured, change):
    user = principal()
    request = gate(user)
    if change == 'disabled':
        User.objects.filter(pk=user.pk).update(mfa_enabled=False)
    elif change == 'no_secret':
        User.objects.filter(pk=user.pk).update(mfa_secret_encrypted='')
    elif change == 'no_mfa':
        request.session['mfa_verified'] = False
    elif change == 'session':
        User.objects.filter(pk=user.pk).update(session_version=user.session_version + 1)
    elif change == 'inactive':
        User.objects.filter(pk=user.pk).update(is_active=False)
    else:
        UserRole.objects.create(user=user, role=Role.objects.get(slug='conta-de-servico'))
    assert wordpress_auth_gate(request).status_code == 403


def test_forwarded_headers_cannot_replace_edge_proof(configured):
    request = gate(principal())
    request.META['HTTP_X_KAIROS_PROXY'] = 'attacker'
    assert wordpress_auth_gate(request).status_code == 403


@pytest.mark.parametrize('headers', [{'HTTP_AUTHORIZATION': 'Basic user-password'}, {'HTTP_COOKIE': 'wordpress_logged_in_hash=plain-wp-session'}, {'HTTP_X_HTTP_METHOD_OVERRIDE': 'DELETE'}])
def test_native_wordpress_auth_and_override_require_kairos_mfa(configured, headers):
    assert wordpress_auth_gate(gate(uri='/wp-json/wp/v2/posts', **headers)).status_code == 403


def test_attestation_contract_no_secrets_and_unique_nonce(configured):
    request = gate(principal(), method='POST', uri='/wp-admin/post.php?id=1', HTTP_COOKIE='sessionid=test', HTTP_AUTHORIZATION='Basic fixture')
    with patch('core.wordpress_auth.time.time', return_value=1800000000), patch('core.wordpress_auth.secrets.token_hex', return_value='a' * 32):
        response = wordpress_auth_gate(request)
    assert response.status_code == 204
    fields = ['1800000000', 'admin', 'a' * 32, 'POST', '/wp-admin/post.php?id=1']
    fields += [hashlib.sha256(value.encode()).hexdigest() for value in ['sessionid=test', 'Basic fixture', '']]
    expected = hmac.new(KEY.encode(), '\n'.join(fields).encode(), hashlib.sha256).hexdigest()
    assert response['X-Kairos-Wp-Gate'] == f'1800000000.admin.{"a" * 32}.{expected}'
    assert KEY not in str(response.headers) and PROOF not in str(response.headers)
    assert wordpress_auth_gate(request)['X-Kairos-Wp-Gate'] != wordpress_auth_gate(request)['X-Kairos-Wp-Gate']


def test_missing_signing_key_is_fail_closed(configured, settings):
    settings.KAIROS_WORDPRESS_GATE_KEY = ''
    assert wordpress_auth_gate(gate(uri='/')).status_code == 503


def test_caddy_internal_route_is_private_and_attestation_not_public():
    root = Path(os.getenv('KAIROS_TEST_REPOSITORY') or Path(__file__).parents[3])
    source = (root / 'infra/caddy/Caddyfile').read_text()
    assert 'handle /api/internal/*' in source and 'respond "Not found" 404' in source
    assert 'request_header -X-Kairos-Wp-Gate' in source
    assert 'copy_headers X-Kairos-Wp-Gate' in source
    assert 'header_down -X-Kairos-Wp-Gate' in source


def test_repeated_query_limit_is_fail_closed():
    assert request_class('GET', '/?' + '&'.join(f'x{i}=1' for i in range(101))) == 'deny'
