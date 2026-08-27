# WordPress and Elementor

WordPress is the editable institutional surface only. It does not store attempts, scores, vector data, legal canonical records, application sessions, or private student profiles.

The deployment pins WordPress 7.1.0, Hello Elementor 3.4.9, Elementor Free 4.2.3, and WP-CLI 2.12.0. Elementor Pro is not installed without a valid owner-provided license. Missing Pro features may be implemented only with a legitimate, maintained plugin after documenting version, license, source, date, purpose, and reason.

The Kairós symbol and site icon are uploaded to Media Library and assigned through WordPress administrative settings. They are not hardcoded into a theme. The 26 supplied palette values are registered in the active Elementor Site Kit, and the four system typography roles use Montserrat. The 400, 500, 600, and 700 weights are self-hosted under the uploads directory using the SIL Open Font License.

The small mandatory MU plugin only enqueues the versioned brand stylesheet and enables the administrative custom-logo mechanism. The stylesheet consumes Elementor global variables and centralizes the fallback palette, local font faces, keyboard focus, and `prefers-reduced-motion`; it contains no page content. The initial seed is one-time so later page, menu, logo, favicon, color, and typography edits are preserved across bootstrap reruns.

Initial pages: Início, O Kairós, Estudar, Primeira Fase OAB, Segunda Fase OAB, Simulados, Casos Práticos, Biblioteca Jurídica, Consultor Kairós, Meu Desempenho, Como Funciona, Termos, Privacidade, and Contato.

The primary menu sends authenticated destinations directly to `/app`. Public pages remain editable with WordPress blocks and can be opened in Elementor. Popup Builder is intentionally pending because no Elementor Pro license was supplied.
