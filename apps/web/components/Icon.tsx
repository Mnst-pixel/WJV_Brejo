import type {SVGProps} from "react";

export type IconName =
  | "home" | "book" | "question" | "clipboard" | "document" | "library" | "chat" | "folder"
  | "target" | "accessibility" | "settings" | "user" | "menu" | "arrow" | "clock" | "play"
  | "pause" | "scales" | "check" | "search" | "refresh" | "trend" | "close" | "upload"
  | "note" | "spark" | "more";

const paths: Record<IconName, React.ReactNode> = {
  home: <><path d="m3 11 9-7 9 7"/><path d="M5.5 10v10h13V10"/><path d="M9 20v-6h6v6"/></>,
  book: <><path d="M3.5 5.5A4.5 4.5 0 0 1 8 3h3v17H8a4.5 4.5 0 0 0-4.5 2Z"/><path d="M20.5 5.5A4.5 4.5 0 0 0 16 3h-3v17h3a4.5 4.5 0 0 1 4.5 2Z"/></>,
  question: <><circle cx="12" cy="12" r="9"/><path d="M9.8 9a2.4 2.4 0 1 1 3.1 2.3c-.9.4-.9 1-.9 1.7"/><path d="M12 17h.01"/></>,
  clipboard: <><rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4.5V3h6v1.5"/><path d="m9 12 2 2 4-4"/><path d="M9 18h6"/></>,
  document: <><path d="M6 2.5h8l4 4V21H6Z"/><path d="M14 2.5v5h4"/><path d="M9 12h6M9 16h6"/></>,
  library: <><path d="M4 4h4v16H4zM10 4h4v16h-4zM16 5l3-1 3 15-3 1z"/></>,
  chat: <><path d="M4 5h12a3 3 0 0 1 3 3v4a3 3 0 0 1-3 3H9l-5 4v-4a3 3 0 0 1-2-3V8a3 3 0 0 1 2-3Z"/><path d="M8 9h5"/></>,
  folder: <path d="M3 6h7l2 2h9v11H3Z"/>,
  target: <><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v4M22 12h-4M12 22v-4M2 12h4"/></>,
  accessibility: <><circle cx="12" cy="4" r="2"/><path d="M4 8h16M12 8v13M8 21l4-7 4 7"/></>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/></>,
  user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16"/>,
  arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
  play: <path d="m9 7 8 5-8 5Z"/>,
  pause: <path d="M9 7v10M15 7v10"/>,
  scales: <><path d="M12 3v18M5 6h14M7 6l-4 8h8L7 6Zm10 0-4 8h8l-4-8ZM8 21h8"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  search: <><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></>,
  refresh: <><path d="M20 7v5h-5"/><path d="M19 12a7 7 0 1 0-2 5"/></>,
  trend: <path d="m4 17 5-5 4 3 7-8M15 7h5v5"/>,
  close: <path d="M6 6l12 12M18 6 6 18"/>,
  upload: <><path d="M12 16V4m-4 4 4-4 4 4"/><path d="M4 15v5h16v-5"/></>,
  note: <><path d="M5 3h14v18H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></>,
  spark: <path d="m12 2 1.7 5.3L19 9l-5.3 1.7L12 16l-1.7-5.3L5 9l5.3-1.7Z"/>,
  more: <><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></>,
};

export function Icon({name, ...props}: {name: IconName} & SVGProps<SVGSVGElement>) {
  return (
    <svg aria-hidden="true" fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.75" viewBox="0 0 24 24" {...props}>
      {paths[name]}
    </svg>
  );
}
