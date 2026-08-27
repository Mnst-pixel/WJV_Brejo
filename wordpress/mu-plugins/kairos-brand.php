<?php
/**
 * Plugin Name: Kairós Brand Foundation
 * Description: Carrega a tipografia local e a camada mínima de acessibilidade da identidade Kairós.
 * Version: 1.0.0
 * License: GPL-2.0-or-later
 */

if (!defined('ABSPATH')) {
    exit;
}

add_action('wp_enqueue_scripts', static function (): void {
    $uploads = wp_upload_dir();
    $path = trailingslashit($uploads['basedir']) . 'kairos/kairos-site.css';
    $url = trailingslashit($uploads['baseurl']) . 'kairos/kairos-site.css';
    if (is_readable($path)) {
        wp_enqueue_style('kairos-brand', $url, [], (string) filemtime($path));
    }
});

add_action('after_setup_theme', static function (): void {
    add_theme_support('custom-logo', [
        'height' => 220,
        'width' => 220,
        'flex-height' => true,
        'flex-width' => true,
    ]);
});
