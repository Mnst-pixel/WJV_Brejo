<?php
/**
 * Plugin Name: Kairós Administrative MFA Gate
 * Description: Requires an internal, request-bound Kairós authorization proof.
 * Version: 1.0.0
 * License: GPL-2.0-or-later
 */

if (!defined('ABSPATH')) {
    exit;
}

/** Pure verifier also exercised by the isolated PHP contract tests. */
function kairos_gate_verify(string $token, string $key, array $server, int $now): ?array {
    if (strlen($key) < 64 || !preg_match('/^([0-9]{10})\.(admin|public)\.([a-f0-9]{32})\.([a-f0-9]{64})$/D', $token, $parts)) {
        return null;
    }
    $age = $now - (int) $parts[1];
    if ($age < -2 || $age > 10) {
        return null;
    }
    $fields = [$parts[1], $parts[2], $parts[3], $server['REQUEST_METHOD'] ?? '', $server['REQUEST_URI'] ?? ''];
    foreach (['HTTP_COOKIE', 'HTTP_AUTHORIZATION', 'HTTP_X_HTTP_METHOD_OVERRIDE'] as $name) {
        $fields[] = hash('sha256', $server[$name] ?? '');
    }
    $signature = hash_hmac('sha256', implode("\n", $fields), $key);
    return hash_equals($signature, $parts[4]) ? ['class' => $parts[2], 'nonce' => $parts[3], 'issued' => (int) $parts[1]] : null;
}

/** Atomic INSERT claims a nonce once across all Apache processes. */
function kairos_gate_claim(array $claim): bool {
    global $wpdb;
    $prefix = '_kairos_gate_nonce_';
    $pattern = $wpdb->esc_like($prefix) . '%';
    // Only our expired, ephemeral replay records are removed; no content/options elsewhere.
    $wpdb->query($wpdb->prepare("DELETE FROM {$wpdb->options} WHERE option_name LIKE %s AND CAST(option_value AS UNSIGNED) < %d LIMIT 256", $pattern, time() - 12));
    $count = $wpdb->get_var($wpdb->prepare("SELECT COUNT(*) FROM {$wpdb->options} WHERE option_name LIKE %s", $pattern));
    if ($count === null || (int) $count >= 4096) {
        return false;
    }
    return $wpdb->query($wpdb->prepare("INSERT IGNORE INTO {$wpdb->options} (option_name, option_value, autoload) VALUES (%s, %s, 'no')", $prefix . $claim['nonce'], (string) $claim['issued'])) === 1;
}

function kairos_gate_denied(): void {
    header('Cache-Control: private, no-store');
    header('X-Content-Type-Options: nosniff');
    http_response_code(403);
    exit('Kairós administrative authorization required.');
}

// CLI remains an explicitly privileged operations interface; HTTP cannot set PHP_SAPI.
if (PHP_SAPI !== 'cli') {
    $kairos_claim = kairos_gate_verify($_SERVER['HTTP_X_KAIROS_WP_GATE'] ?? '', getenv('KAIROS_WORDPRESS_GATE_KEY') ?: '', $_SERVER, time());
    if ($kairos_claim === null || ($kairos_claim['class'] === 'admin' && !kairos_gate_claim($kairos_claim))) {
        kairos_gate_denied();
    }
    $GLOBALS['kairos_admin_authorized'] = $kairos_claim['class'] === 'admin';
    unset($_SERVER['HTTP_X_KAIROS_WP_GATE'], $kairos_claim);
    // Authenticated WordPress identity may never be obtained from a public proof.
    add_filter('determine_current_user', static function ($user) {
        return !empty($GLOBALS['kairos_admin_authorized']) ? $user : 0;
    }, PHP_INT_MAX);
    add_filter('authenticate', static function ($user) {
        return !empty($GLOBALS['kairos_admin_authorized']) ? $user : new WP_Error('kairos_mfa_required', 'Kairós MFA required.');
    }, PHP_INT_MAX);
    add_action('admin_init', static function (): void {
        if (empty($GLOBALS['kairos_admin_authorized'])) {
            kairos_gate_denied();
        }
    }, -PHP_INT_MAX);
    add_filter('rest_pre_dispatch', static function ($result, $server, $request) {
        if (empty($GLOBALS['kairos_admin_authorized']) && (!in_array($request->get_method(), ['GET', 'HEAD', 'OPTIONS'], true) || $request->get_param('context') === 'edit')) {
            return new WP_Error('kairos_mfa_required', 'Kairós MFA required.', ['status' => 403]);
        }
        return $result;
    }, -PHP_INT_MAX, 3);
}

add_filter('xmlrpc_enabled', '__return_false', PHP_INT_MAX);
add_filter('wp_is_application_passwords_available', '__return_false', PHP_INT_MAX);
add_filter('wp_is_application_passwords_available_for_user', '__return_false', PHP_INT_MAX);
