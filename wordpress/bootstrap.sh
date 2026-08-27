#!/bin/sh
set -eu

export WP_CLI_CACHE_DIR="${WP_CLI_CACHE_DIR:-/tmp/wp-cli-cache}"
mkdir -p "$WP_CLI_CACHE_DIR"

for required in \
  /assets/Simbolo.png \
  /assets/Mini-Icone.png \
  /assets/kairos-site.css \
  /config/elementor-site-settings.json \
  /mu-plugins/kairos-brand.php; do
  [ -r "$required" ] || { echo "Required WordPress seed asset is unreadable: $required" >&2; exit 1; }
done


cd /var/www/html

until [ -f wp-includes/version.php ]; do sleep 2; done
until wp db check --quiet; do sleep 3; done

if ! wp core is-installed; then
  wp core install \
    --url="$KAIROS_BASE_URL" \
    --title="Kairós" \
    --admin_user="$WORDPRESS_ADMIN_USER" \
    --admin_password="$WORDPRESS_ADMIN_PASSWORD" \
    --admin_email="$WORDPRESS_ADMIN_EMAIL" \
    --skip-email
fi

# Reconcile non-secret profile fields without changing the existing password.
wp user update "$WORDPRESS_ADMIN_USER" \
  --user_email="$WORDPRESS_ADMIN_EMAIL" \
  --display_name="${WORDPRESS_ADMIN_DISPLAY_NAME:-Vinícius}" >/dev/null

if [ "$(wp theme get hello-elementor --field=version 2>/dev/null || true)" != "3.4.9" ]; then
  wp theme install hello-elementor --version=3.4.9 --force
fi
wp theme activate hello-elementor

if [ "$(wp plugin get elementor --field=version 2>/dev/null || true)" != "4.2.3" ]; then
  wp plugin install elementor --version=4.2.3 --force
fi
wp plugin activate elementor
wp language core install pt_BR --activate || true

create_page() {
  title="$1"
  slug="$2"
  file="$3"
  existing="$(wp post list --post_type=page --name="$slug" --field=ID --format=ids)"
  if [ -z "$existing" ]; then
    wp post create "$file" --post_type=page --post_title="$title" --post_name="$slug" --post_status=publish >/dev/null
  fi
}

create_page "Início" "inicio" /seed/inicio.html
create_page "O Kairós" "o-kairos" /seed/o-kairos.html
create_page "Estudar" "estudar" /seed/estudar.html
create_page "Primeira Fase OAB" "primeira-fase-oab" /seed/primeira-fase-oab.html
create_page "Segunda Fase OAB" "segunda-fase-oab" /seed/segunda-fase-oab.html
create_page "Simulados" "simulados" /seed/simulados.html
create_page "Casos Práticos" "casos-praticos" /seed/casos-praticos.html
create_page "Biblioteca Jurídica" "biblioteca-juridica" /seed/biblioteca-juridica.html
create_page "Consultor Kairós" "consultor-kairos" /seed/consultor-kairos.html
create_page "Meu Desempenho" "meu-desempenho" /seed/meu-desempenho.html
create_page "Como Funciona" "como-funciona" /seed/como-funciona.html
create_page "Termos" "termos" /seed/termos.html
create_page "Privacidade" "privacidade" /seed/privacidade.html
create_page "Contato" "contato" /seed/contato.html

home_id="$(wp post list --post_type=page --name=inicio --field=ID --format=ids)"

if ! wp option get kairos_initial_site_seed >/dev/null 2>&1; then
  wp rewrite structure '/%postname%/' --hard
  wp option update show_on_front page
  wp option update page_on_front "$home_id"
  wp option update blog_public 0
  wp option update users_can_register 0
  wp option update default_comment_status closed
  wp option update default_ping_status closed
  wp option update timezone_string America/Sao_Paulo
  wp option update date_format 'd/m/Y'
  wp option update time_format 'H:i'
  wp option update blogdescription 'Seu tempo de aprovação, com método e fontes.'
  wp option update kairos_initial_site_seed 1
fi

if ! wp option get kairos_logo_attachment_id >/dev/null 2>&1; then
  logo_id="$(wp media import /assets/Simbolo.png --title='Símbolo Kairós' --alt='Símbolo do Kairós' --porcelain)"
  wp option update kairos_logo_attachment_id "$logo_id"
  wp theme mod set custom_logo "$logo_id"
fi

if ! wp option get kairos_icon_attachment_id >/dev/null 2>&1; then
  icon_id="$(wp media import '/assets/Mini-Icone.png' --title='Mini ícone Kairós' --alt='Mini ícone do Kairós' --porcelain)"
  wp option update kairos_icon_attachment_id "$icon_id"
  wp option update site_icon "$icon_id"
fi

if ! wp option get kairos_elementor_seed_version >/dev/null 2>&1; then
  kit_id="$(wp option get elementor_active_kit 2>/dev/null || true)"
  if [ -z "$kit_id" ] || [ "$kit_id" = "0" ]; then
    kit_id="$(wp post create --post_type=elementor_library --post_title='Kairós Site Kit' --post_status=publish --porcelain)"
    wp post meta update "$kit_id" _elementor_template_type kit
    wp option update elementor_active_kit "$kit_id"
  fi
  wp post meta update "$kit_id" _elementor_page_settings "$(cat /config/elementor-site-settings.json)" --format=json
  wp option update elementor_disable_color_schemes yes
  wp option update elementor_disable_typography_schemes yes
  wp option update elementor_global_image_lightbox yes
  wp option update kairos_elementor_seed_version 1
fi

mkdir -p wp-content/uploads/kairos/fonts wp-content/mu-plugins
cp /assets/fonts/montserrat-*.woff2 wp-content/uploads/kairos/fonts/
cp /assets/kairos-site.css wp-content/uploads/kairos/kairos-site.css
cp /mu-plugins/kairos-brand.php wp-content/mu-plugins/kairos-brand.php

if ! wp menu list --fields=slug --format=csv | grep -q '^kairos-primary$'; then
  wp menu create kairos-primary >/dev/null
  wp menu item add-post kairos-primary "$home_id" --title='Início' >/dev/null
  wp menu item add-post kairos-primary "$(wp post list --post_type=page --name=o-kairos --field=ID --format=ids)" --title='O Kairós' >/dev/null
  wp menu item add-custom kairos-primary 'Estudar' "$KAIROS_BASE_URL/app/estudar" >/dev/null
  wp menu item add-post kairos-primary "$(wp post list --post_type=page --name=primeira-fase-oab --field=ID --format=ids)" --title='Primeira Fase' >/dev/null
  wp menu item add-post kairos-primary "$(wp post list --post_type=page --name=segunda-fase-oab --field=ID --format=ids)" --title='Segunda Fase' >/dev/null
  wp menu item add-custom kairos-primary 'Biblioteca' "$KAIROS_BASE_URL/app/biblioteca" >/dev/null
  wp menu item add-custom kairos-primary 'Consultor' "$KAIROS_BASE_URL/app/consultor" >/dev/null
  wp menu item add-post kairos-primary "$(wp post list --post_type=page --name=contato --field=ID --format=ids)" --title='Contato' >/dev/null
fi

if ! wp menu item list kairos-primary --fields=title --format=csv | grep -q '^Entrar$'; then
  wp menu item add-custom kairos-primary 'Entrar' "$KAIROS_BASE_URL/app/login" >/dev/null
fi

# Location assignment must also run after an interrupted or partial first seed.
location="$(wp menu location list --fields=location --format=csv | tail -n +2 | head -n 1 || true)"
if [ -n "$location" ]; then wp menu location assign kairos-primary "$location" || true; fi

wp cache flush >/dev/null || true

echo "WORDPRESS_BOOTSTRAP=PASS"
