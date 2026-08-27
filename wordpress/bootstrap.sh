#!/bin/sh
set -eu

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

wp theme install hello-elementor --version=3.4.9 --activate --force
wp plugin install elementor --version=4.2.3 --activate --force
wp rewrite structure '/%postname%/' --hard

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
create_page "Sobre" "sobre" /seed/sobre.html
create_page "Conteúdos" "conteudos" /seed/conteudos.html
create_page "Contato" "contato" /seed/contato.html

home_id="$(wp post list --post_type=page --name=inicio --field=ID --format=ids)"
wp option update show_on_front page
wp option update page_on_front "$home_id"
wp option update blog_public 0

echo "WORDPRESS_BOOTSTRAP=PASS"
