"use client";

import Image from "next/image";
import Link from "next/link";
import {usePathname} from "next/navigation";
import {useEffect, useState} from "react";

import {Icon, type IconName} from "./Icon";

const navigation: {label: string; href: string; icon: IconName}[] = [
  {label: "Visão geral", href: "/", icon: "home"},
  {label: "Estudar", href: "/estudar", icon: "book"},
  {label: "Questões", href: "/questoes", icon: "question"},
  {label: "Simulados", href: "/simulados", icon: "clipboard"},
  {label: "Segunda fase", href: "/segunda-fase", icon: "document"},
  {label: "Biblioteca", href: "/biblioteca", icon: "library"},
  {label: "Consultor", href: "/consultor", icon: "chat"},
  {label: "Arquivos", href: "/arquivos", icon: "folder"},
  {label: "Metas", href: "/metas", icon: "target"},
];

const mobileNavigation = [
  navigation[0], navigation[1], navigation[3], navigation[6], {label: "Mais", href: "#menu", icon: "more" as IconName},
];

export function AppShell({children, userName}: {children: React.ReactNode; userName: string}) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const [accessibilityOpen, setAccessibilityOpen] = useState(false);
  const [textScale, setTextScale] = useState(100);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [focusMode, setFocusMode] = useState(false);

  useEffect(() => {
    document.documentElement.style.setProperty("--user-text-scale", `${textScale / 100}`);
    document.documentElement.dataset.reduceMotion = String(reducedMotion);
    document.documentElement.dataset.focusMode = String(focusMode);
  }, [textScale, reducedMotion, focusMode]);

  const isActive = (href: string) => href === "/" ? pathname === "/app" || pathname === "/app/" : pathname.startsWith(`/app${href}`);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#conteudo-principal">Ir para o conteúdo principal</a>
      <aside className="sidebar" aria-label="Navegação principal">
        <Link className="brand" href="/" aria-label="Kairós — visão geral">
          <span className="brand-art"><Image alt="" fill priority sizes="144px" src="/app/simbolo.png" /></span>
          <span>Kairós</span>
        </Link>
        <nav className="primary-nav">
          {navigation.map((item) => (
            <Link aria-current={isActive(item.href) ? "page" : undefined} className={isActive(item.href) ? "nav-item active" : "nav-item"} href={item.href} key={item.href}>
              <Icon name={item.icon} /><span>{item.label}</span>
            </Link>
          ))}
        </nav>
        <div className="sidebar-utilities">
          <button className="nav-item" onClick={() => setAccessibilityOpen(true)} type="button"><Icon name="accessibility"/><span>Acessibilidade</span></button>
          <Link className="nav-item" href="/configuracoes"><Icon name="settings"/><span>Configurações</span></Link>
          <button className="profile-button" type="button"><span className="profile-initial">{userName.slice(0, 1)}</span><span>{userName}</span></button>
        </div>
      </aside>

      <header className="mobile-header">
        <Link className="mobile-brand" href="/"><Image alt="Símbolo do Kairós" height={48} priority src="/app/simbolo.png" width={48}/><span>Kairós</span></Link>
        <button className="mobile-user" type="button"><Icon name="user"/><span>{userName}</span></button>
        <button aria-expanded={menuOpen} aria-label={menuOpen ? "Fechar menu" : "Abrir menu"} className="icon-button" onClick={() => setMenuOpen(!menuOpen)} type="button"><Icon name={menuOpen ? "close" : "menu"}/></button>
      </header>

      {menuOpen && (
        <div className="mobile-drawer" id="menu">
          <nav aria-label="Menu completo">
            {navigation.map((item) => <Link className="nav-item" href={item.href} key={item.href} onClick={() => setMenuOpen(false)}><Icon name={item.icon}/>{item.label}</Link>)}
          </nav>
          <button className="nav-item" onClick={() => {setMenuOpen(false); setAccessibilityOpen(true);}} type="button"><Icon name="accessibility"/>Acessibilidade</button>
        </div>
      )}

      <main id="conteudo-principal">{children}</main>

      <nav className="mobile-bottom-nav" aria-label="Navegação rápida">
        {mobileNavigation.map((item) => item.href === "#menu" ? (
          <button key={item.label} onClick={() => setMenuOpen(true)} type="button"><Icon name={item.icon}/><span>{item.label}</span></button>
        ) : (
          <Link aria-current={isActive(item.href) ? "page" : undefined} className={isActive(item.href) ? "active" : ""} href={item.href} key={item.href}><Icon name={item.icon}/><span>{item.label}</span></Link>
        ))}
      </nav>

      {accessibilityOpen && (
        <div className="modal-backdrop" onMouseDown={() => setAccessibilityOpen(false)}>
          <section aria-labelledby="accessibility-title" aria-modal="true" className="accessibility-panel" onMouseDown={(event) => event.stopPropagation()} role="dialog">
            <div className="panel-heading"><div><h2 id="accessibility-title">Acessibilidade</h2><p>Ajuste a experiência sem perder seu progresso.</p></div><button aria-label="Fechar" className="icon-button" onClick={() => setAccessibilityOpen(false)} type="button"><Icon name="close"/></button></div>
            <label className="range-control" htmlFor="text-scale"><span>Tamanho do texto</span><strong>{textScale}%</strong></label>
            <input id="text-scale" max="125" min="90" onChange={(event) => setTextScale(Number(event.target.value))} step="5" type="range" value={textScale}/>
            <label className="switch-row"><span><strong>Movimento reduzido</strong><small>Remove transições não essenciais.</small></span><input checked={reducedMotion} onChange={(event) => setReducedMotion(event.target.checked)} type="checkbox"/></label>
            <label className="switch-row"><span><strong>Modo foco</strong><small>Oculta áreas secundárias enquanto você estuda.</small></span><input checked={focusMode} onChange={(event) => setFocusMode(event.target.checked)} type="checkbox"/></label>
          </section>
        </div>
      )}
    </div>
  );
}
