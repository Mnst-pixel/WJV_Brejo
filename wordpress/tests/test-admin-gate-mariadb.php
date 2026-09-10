<?php
// Real WordPress wpdb and MariaDB; disposable schema only, no production content.
if (getenv('KAIROS_TEST_WP_DB_HOST') !== 'kairos-test-mariadb' || getenv('KAIROS_TEST_WP_DB_NAME') !== 'kairos_gate_test') {
    throw new RuntimeException('Disposable MariaDB fixture required');
}
define('ABSPATH', '/usr/src/wordpress/');
define('WPINC', 'wp-includes');
define('WP_DEBUG', false);
define('DB_CHARSET', 'utf8mb4');
define('DB_COLLATE', '');
// Only WordPress hooks/diagnostics are shimmed; SQL, quoting, affected rows,
// connections and the unique index execute through the vendor wpdb class.
function add_filter(...$args) { return true; }
function apply_filters($name, $value, ...$args) { return $value; }
function has_filter(...$args) { return false; }
function did_action(...$args) { return 1; }
function is_multisite() { return false; }
function __($value, ...$args) { return $value; }
function wp_load_translations_early() {}
function wp_debug_backtrace_summary(...$args) { return 'isolated fixture'; }
function wp_get_wp_version() { return '7.1'; }
function wp_die(...$args) { throw new RuntimeException('WordPress database fixture unavailable'); }
function _doing_it_wrong(...$args) { throw new RuntimeException('Invalid WordPress database invocation'); }
function check($value, $label) {
    if (!$value) { throw new RuntimeException($label); }
}
require ABSPATH . WPINC . '/class-wpdb.php';
$wpdb = new wpdb('kairos_gate_test', getenv('KAIROS_TEST_WP_DB_PASSWORD'), 'kairos_gate_test', 'kairos-test-mariadb');
$wpdb->suppress_errors(true);
$wpdb->set_prefix('kairos_fixture_');
require dirname(__DIR__) . '/mu-plugins/kairos-admin-gate.php';

if (($argv[1] ?? '') === 'claim') {
    check(preg_match('/^[a-f0-9]{32}$/D', $argv[2] ?? '') === 1, 'synthetic nonce');
    echo "READY\n";
    fflush(STDOUT);
    check(fread(STDIN, 1) === 'x', 'start barrier');
    echo kairos_gate_claim(['nonce' => $argv[2], 'issued' => time()]) ? "CLAIMED\n" : "DENIED\n";
    exit(0);
}

check($wpdb->query("CREATE TABLE {$wpdb->options} (
    option_id bigint unsigned NOT NULL AUTO_INCREMENT,
    option_name varchar(191) NOT NULL DEFAULT '',
    option_value longtext NOT NULL,
    autoload varchar(20) NOT NULL DEFAULT 'yes',
    PRIMARY KEY (option_id), UNIQUE KEY option_name (option_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci") !== false, 'fresh options table');

$nonce = bin2hex(random_bytes(16));
$children = [];
try {
    for ($index = 0; $index < 12; $index++) {
        $pipes = [];
        $process = proc_open([PHP_BINARY, __FILE__, 'claim', $nonce], [0 => ['pipe', 'r'], 1 => ['pipe', 'w'], 2 => ['pipe', 'w']], $pipes);
        check(is_resource($process), 'independent claimant process');
        stream_set_timeout($pipes[1], 10);
        $children[] = [$process, $pipes];
    }
    foreach ($children as [$process, $pipes]) {
        check(trim(fgets($pipes[1]) ?: '') === 'READY', 'all database sessions ready');
    }
    foreach ($children as [$process, $pipes]) { fwrite($pipes[0], 'x'); fflush($pipes[0]); }
    $winners = 0;
    foreach ($children as [$process, $pipes]) {
        $result = trim(fgets($pipes[1]) ?: '');
        check(in_array($result, ['CLAIMED', 'DENIED'], true), 'claim result');
        $winners += (int) ($result === 'CLAIMED');
    }
    check($winners === 1, 'exactly one concurrent replay accepted');
} finally {
    foreach ($children as [$process, $pipes]) {
        foreach ($pipes as $pipe) { fclose($pipe); }
        $status = proc_get_status($process);
        if ($status['running']) { proc_terminate($process); }
        proc_close($process);
    }
}
check(!kairos_gate_claim(['nonce' => $nonce, 'issued' => time()]), 'later replay denied');
check(kairos_gate_claim(['nonce' => bin2hex(random_bytes(16)), 'issued' => time()]), 'distinct request accepted');
check((int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->options} WHERE autoload <> 'no'") === 0, 'no nonce autoload');

$unrelated = ['siteurl', 'XkairosXgateXnonceXunrelated', '_kairos_gate_nonceXunrelated'];
foreach ($unrelated as $name) {
    check($wpdb->insert($wpdb->options, ['option_name' => $name, 'option_value' => 'human-content', 'autoload' => 'yes']) === 1, 'unrelated option fixture');
}
for ($index = 0; $index < 300; $index++) {
    check($wpdb->insert($wpdb->options, ['option_name' => '_kairos_gate_nonce_' . bin2hex(random_bytes(16)), 'option_value' => (string) (time() - 60), 'autoload' => 'no']) === 1, 'expired nonce fixture');
}
check(kairos_gate_claim(['nonce' => bin2hex(random_bytes(16)), 'issued' => time()]), 'claim prunes expired nonces');
check((int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->options} WHERE autoload = 'no' AND CAST(option_value AS UNSIGNED) < UNIX_TIMESTAMP() - 12") === 44, 'cleanup limited to 256');
foreach ($unrelated as $name) {
    check($wpdb->get_var($wpdb->prepare("SELECT option_value FROM {$wpdb->options} WHERE option_name = %s", $name)) === 'human-content', 'unrelated content preserved');
}
// Reset only this isolated test table, then test saturation and SQL failure.
check($wpdb->query("DELETE FROM {$wpdb->options}") !== false, 'fixture reset');
$issued = (string) (time() + 3600); // Stable capacity fixture; never an accepted HMAC claim.
$rows = [];
for ($index = 0; $index < 4096; $index++) {
    $rows[] = $wpdb->prepare("(%s, %s, 'no')", '_kairos_gate_nonce_' . bin2hex(random_bytes(16)), $issued);
}
check($wpdb->query("INSERT INTO {$wpdb->options} (option_name, option_value, autoload) VALUES " . implode(',', $rows)) === 4096, 'capacity fixture');
check(!kairos_gate_claim(['nonce' => bin2hex(random_bytes(16)), 'issued' => time()]), 'saturation fails closed');
check($wpdb->query("DROP TABLE {$wpdb->options}") !== false, 'disposable table removal');
check(!kairos_gate_claim(['nonce' => bin2hex(random_bytes(16)), 'issued' => time()]), 'database error fails closed');
echo "WORDPRESS_GATE_MARIADB=PASS concurrent_claimants=12 accepted=1\n";
