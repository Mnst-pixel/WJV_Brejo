<?php
// php wordpress/tests/test-admin-gate.php (no WordPress database or credentials).
define('ABSPATH', __DIR__);
$filters = [];
function add_filter($name, $callback, $priority = 10, $args = 1) {
    global $filters;
    $filters[$name] = $callback;
}
function check($value, $label) {
    if (!$value) {
        throw new RuntimeException($label);
    }
}
require dirname(__DIR__) . '/mu-plugins/kairos-admin-gate.php';
$key = str_repeat('wordpress-fixture-', 8);
$server = ['REQUEST_METHOD' => 'POST', 'REQUEST_URI' => '/wp-admin/post.php?id=1', 'HTTP_COOKIE' => 'sessionid=test', 'HTTP_AUTHORIZATION' => 'Basic fixture'];
$fields = ['1800000000', 'admin', str_repeat('a', 32), $server['REQUEST_METHOD'], $server['REQUEST_URI']];
foreach (['HTTP_COOKIE', 'HTTP_AUTHORIZATION', 'HTTP_X_HTTP_METHOD_OVERRIDE'] as $name) {
    $fields[] = hash('sha256', $server[$name] ?? '');
}
$token = '1800000000.admin.' . str_repeat('a', 32) . '.' . hash_hmac('sha256', implode("\n", $fields), $key);
$claim = kairos_gate_verify($token, $key, $server, 1800000000);
check($claim !== null && $claim['class'] === 'admin', 'valid request');
check(kairos_gate_verify($token, $key, $server, 1800000011) === null, 'expired');
check(kairos_gate_verify($token, $key, $server, 1799999997) === null, 'future');
check(kairos_gate_verify($token, 'wrong', $server, 1800000000) === null, 'short key');
check(kairos_gate_verify($token, str_repeat('b', 64), $server, 1800000000) === null, 'wrong key');
check(kairos_gate_verify(str_replace('.admin.', '.public.', $token), $key, $server, 1800000000) === null, 'class tampering');
foreach (['REQUEST_METHOD', 'REQUEST_URI', 'HTTP_COOKIE', 'HTTP_AUTHORIZATION', 'HTTP_X_HTTP_METHOD_OVERRIDE'] as $name) {
    $changed = $server;
    $changed[$name] = ($changed[$name] ?? '') . 'changed';
    check(kairos_gate_verify($token, $key, $changed, 1800000000) === null, 'bound ' . $name);
}
class FakeNonceDB {
    public $options = 'fixture_options';
    public $seen = false;
    public $full = false;
    function esc_like($value) { return addcslashes($value, '_%\\'); }
    function prepare($sql, ...$args) { return $sql; }
    function get_var($sql) { return $this->full ? 4096 : 0; }
    function query($sql) {
        if (str_starts_with($sql, 'INSERT')) {
            if ($this->seen) { return 0; }
            $this->seen = true;
            return 1;
        }
        return 0;
    }
}
$wpdb = new FakeNonceDB();
check(kairos_gate_claim($claim), 'first nonce accepted');
check(!kairos_gate_claim($claim), 'replayed nonce denied');
$wpdb = new FakeNonceDB();
$wpdb->full = true;
check(!kairos_gate_claim($claim), 'nonce capacity fail closed');
foreach (['xmlrpc_enabled', 'wp_is_application_passwords_available', 'wp_is_application_passwords_available_for_user'] as $name) {
    check($filters[$name] === '__return_false', 'disabled ' . $name);
}
echo "WORDPRESS_GATE_CONTRACT=PASS\n";
